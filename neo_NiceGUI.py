import os
import re
import time
import queue
import threading
import sqlite3
import psutil
import torch
import http
from datetime import datetime
from nicegui import ui, app
from transformers import AutoConfig, GPTNeoForCausalLM, GPT2Tokenizer
from safetensors.torch import load_file
from PyPDF2 import PdfReader
from docx import Document
from bs4 import BeautifulSoup
import html2text
import argparse
from fastapi import Request, FastAPI
from contextlib import asynccontextmanager
import traceback

# ----------------------------
# LIFESPAN YÖNETİMİ (YENİ YÖNTEM)
# ----------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
	# UI güncelleme kuyruğunu başlat
	db = ChatHistoryDB()
	db._process_ui_updates()
	yield

# ----------------------------
# VERİTABANI YÖNETİMİ (GÜNCELLENDİ)
# ----------------------------
class ChatHistoryDB:
	def __init__(self):
		self.queue = queue.Queue()
		self.ui_update_queue = queue.Queue()
		self.conn = None
		self._init_db()

		# Worker thread'leri başlat
		self.worker_thread = threading.Thread(target=self._db_worker, daemon=True)
		self.ui_update_thread = threading.Thread(target=self._process_ui_updates, daemon=True)

		self.worker_thread.start()
		self.ui_update_thread.start()  # Bu kritik öneme sahip!
		print("DB ve UI Update thread'leri başlatıldı")  # Debug

	def _init_db(self):
		self.conn = sqlite3.connect("chat_history.db", check_same_thread=False)
		self._create_table()

	def _create_table(self):
		c = self.conn.cursor()
		c.execute('''CREATE TABLE IF NOT EXISTS chats
					 (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, user_ip TEXT)''')
		c.execute('''CREATE TABLE IF NOT EXISTS prompts
					 (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, timestamp TEXT,
					 prompt TEXT, response TEXT, FOREIGN KEY (chat_id) REFERENCES chats(id))''')
		self.conn.commit()

	# ----------------------------
	# CALLBACK DESTEKLİ FONKSİYONLAR
	# ----------------------------
	def create_chat(self, user_ip):
		"""Doğrudan chat_id döndüren senkron bir versiyon."""
		response_queue = queue.Queue()

		def _db_task(c, user_ip):
			timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
			c.execute("INSERT INTO chats (timestamp, user_ip) VALUES (?, ?)", (timestamp, user_ip))
			chat_id = c.lastrowid
			response_queue.put(chat_id)
			return chat_id

		self.queue.put((_db_task, (user_ip,), {}))
		return response_queue.get(timeout=10.0)

	def get_chats(self, user_ip, callback=None):
		def _db_task(c, user_ip):
			c.execute("SELECT * FROM chats WHERE user_ip=? ORDER BY timestamp DESC", (user_ip,))
			chats = c.fetchall()
			chat_list = []
			for chat in chats:
				c.execute("SELECT * FROM prompts WHERE chat_id=? ORDER BY timestamp", (chat[0],))
				chat_list.append({"chat": chat, "prompts": c.fetchall()})
			return chat_list
		self.queue.put((_db_task, (user_ip,), {'callback': callback}))

	def save_prompt(self, chat_id, prompt, response, callback=None):
		def _db_task(c, chat_id, prompt, response):
			timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
			c.execute("INSERT INTO prompts (chat_id, timestamp, prompt, response) VALUES (?, ?, ?, ?)",
					 (chat_id, timestamp, prompt, response))
			return True
		self.queue.put((_db_task, (chat_id, prompt, response), {'callback': callback}))

	def delete_chat(self, chat_id, callback=None):
		def _db_task(c, chat_id):
			c.execute("DELETE FROM prompts WHERE chat_id=?", (chat_id,))
			c.execute("DELETE FROM chats WHERE id=?", (chat_id,))
			return True
		self.queue.put((_db_task, (chat_id,), {'callback': callback}))

	# ----------------------------
	# THREAD-SAFE ÇALIŞAN WORKER
	# ----------------------------
	def _db_worker(self):
		while True:
			task = self.queue.get()
			if task is None:
				break

			func, args, kwargs = task
			try:
				c = self.conn.cursor()
				result = func(c, *args)
				self.conn.commit()

				if 'callback' in kwargs and callable(kwargs['callback']):
					self.ui_update_queue.put((kwargs['callback'], result))

			except Exception as e:
				self.conn.rollback()
			finally:
				self.queue.task_done()

	def _process_ui_updates(self):
		while True:
			try:
				callback, result = self.ui_update_queue.get(timeout=1.0)  # 1 saniye timeout
				if callback:
					callback(result)  # Callback'i çalıştır

				self.ui_update_queue.task_done()
			except queue.Empty:
				time.sleep(0.1)  # CPU'yü tüketmemek için kısa bekleme
				continue

# ----------------------------
# OPTİMİZASYON AYARLARI
# ----------------------------
class OptimizationSettings:
	def __init__(self):
		self.cpu_cores = self.detect_cores()
		ui.notify(str(self.detect_cores()) + " işlemci çekirdeği kullanılabilir")
		self.model_params = {
			'max_new_tokens': 300,
			'temperature': 0.75,
			'top_k': 25,
			'low_memory_mode': True,
			'torch_dtype': torch.float16
		}

	@staticmethod
	def detect_cores():
		return psutil.cpu_count(logical=False)

	def update_cores(self, selected_cores):
		p = psutil.Process(os.getpid())
		p.cpu_affinity(selected_cores)

# ----------------------------
# DOSYA İÇERİĞİNİ OKUMA FONKSİYONLARI
# ----------------------------
def read_txt(file_path):
	with open(file_path, 'r', encoding='utf-8') as file:
		return file.read()

def read_pdf(file_path):
	reader = PdfReader(file_path)
	text = ""
	for page in reader.pages:
		text += page.extract_text()
	return text

def read_docx(file_path):
	doc = Document(file_path)
	text = ""
	for para in doc.paragraphs:
		text += para.text + "\n"
	return text

def read_html(file_path):
	with open(file_path, 'r', encoding='utf-8') as file:
		soup = BeautifulSoup(file, 'html.parser')
		return soup.get_text()

def read_markdown(file_path):
	with open(file_path, 'r', encoding='utf-8') as file:
		return file.read()

# ----------------------------
# ANA GUI SINIFI
# ----------------------------
class TasteModelApp:
	def __init__(self):
		try:
			self.model_loaded
		except AttributeError:
			self.model_loaded = False
		try:
			self.response_generated
		except AttributeError:
			self.response_generated = False
		try:
			self.prompt_entered
		except AttributeError:
			self.prompt_entered = False
		self.tokenizer = None
		self.model = None
		self.reference_text = ""
		self.current_chat_id = None
		self.user_ip = None  # Kullanıcı IP'sini saklamak için
		self.queue = queue.Queue()

		# Modeli yüklemek için gerekiyor
		self.local_model_path = "/path/to/your/model/files"
		self.db = ChatHistoryDB()  # So the db can access the app instance
		self.settings = OptimizationSettings()

		# CPU sıcaklığını loglamak için thread başlat
		self.temp_thread = threading.Thread(target=self.log_cpu_temperature, daemon=True)
		self.temp_thread.start()

		# Model yükleme işlemini başlat
		threading.Thread(target=self._load_model, daemon=True).start()

	def _load_model(self):
		try:
			print("Model yükleniyor...")
			self.tokenizer = GPT2Tokenizer.from_pretrained(self.local_model_path)

			# Model konfigürasyonunu yükle
			config = AutoConfig.from_pretrained(self.local_model_path)

			# Modeli safetensors formatında yükle
			model_path = os.path.join(self.local_model_path, "model.safetensors")
			state_dict = load_file(model_path)

			# Modeli oluştur ve state_dict'i yükle
			self.model = GPTNeoForCausalLM.from_pretrained(
				self.local_model_path,
				config=config,
				state_dict=state_dict,
				device_map="cpu",
				low_cpu_mem_usage=self.settings.model_params['low_memory_mode'],
				torch_dtype=self.settings.model_params['torch_dtype']
			).to("cpu")

			self.model_loaded = True  # Set the flag to indicate model is loaded
			print("Model yüklendi!")

		except Exception as e:
			print("Exception occurred in _load_model:")
			traceback.print_exc()  # Print the full stack trace to the console
			with self.main_container:
				ui.notify(f"Model yükleme hatası: {str(e)}")

	def generate_response(self):
		# Thread güvenliği
		if self.prompt_entered:
			with self.db.last_prompt_container:
				ui.notify("Zaten bir yanıt hazırlanıyor!", type='warning')
			return

		self.response_generated = False

		# 1. Model ve chat kontrolü
		if not self.model_loaded:
			with self.db.last_prompt_container:
				ui.notify("Model henüz yüklenmedi. Lütfen bekleyin...", type='negative')
			self.prompt_entered = False
			return

		prompt = self.prompt_entry.value.strip()

		# 2. Prompt al ve boş kontrolü
		if not prompt:
			with self.db.last_prompt_container:
				ui.notify("Prompt boş olamaz!", type='negative')
			self.prompt_entered = False
			return
		else:
			with self.db.last_prompt_container:
				prompt_accepted = ui.notify("Prompt işleniyor...", type='positive')
			self.prompt_entered = True

		# Yeni sohbet kontrolü (DÜZELTME: Artık chat_id dönüyor)
		if not self.current_chat_id:
			self.current_chat_id = self.start_new_chat()
			if not self.current_chat_id:
				self.prompt_entered = False
				return

		# 3. Model parametreleri
		params = {
			'pad_token_id': self.tokenizer.eos_token_id,
			'max_new_tokens': min(int(self.max_tokens.value), 1024),
			'temperature': max(0.1, float(self.temperature.value)),
			'top_k': 25,
			'do_sample': True
		}

		# 4. Metin üretme (Thread içinde)
		def _generate():
			try:
				# Tokenizer ayarları
				self.tokenizer.pad_token = self.tokenizer.eos_token
				inputs = self.tokenizer(prompt, return_tensors="pt", truncation=True).to("cpu")
				inputs['attention_mask'] = inputs['input_ids'].ne(self.tokenizer.pad_token_id).float()

				if not self.response_generated and self.prompt_entered:
					# Prompt ve yanıtı göster
					self.prompt_label.text = "Prompt"
					self.prompt_display.text = prompt
					self.prompt_entry.value = ""
					self.prompt_entry.update()
					self.response_display.text = "Yanıt hazırlanıyor, lütfen bekleyin..."  # Yükleme mesajı

					# Model çalıştırma
					with torch.no_grad():
						outputs = self.model.generate(
							inputs["input_ids"],
							attention_mask=inputs['attention_mask'],
							**params
						)

					response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)

					# Hata kontrolü
					if not response.strip():
						with self.db.last_prompt_container:
							ui.notify("Yanıt boş olamaz!")
						self.prompt_entered = False
						return

					# UI güncellemesini ana thread'e gönder
					def _update_ui():
						self.response_label.text = "Yanıt"
						self.response_display.text = ""
						full_response = response  # Response'u closure'a al

						def _typewriter_step(index=0):
							while index < len(full_response):
								self.response_display.text = full_response[:index]
								time.sleep(0.34)
								index += 1

						self.db.save_prompt(self.current_chat_id, prompt, response, callback=self._schedule_history_refresh)
						self.response_generated = True
						self.prompt_entered = False

						with self.db.last_prompt_container:
							ui.notify("Prompt yanıtlandı", type='positive')
							_typewriter_step(0)  # Efekti başlat
							self.response_label.text = ""
							self.response_display.text = ""
							self.prompt_label.text = ""
							self.prompt_display.text = ""

					# Ana thread'de çalıştır
					with self.db.last_prompt_container:
						ui.timer(0.1, _update_ui, once=True)

			except Exception as e:
				with self.db.last_prompt_container:
					ui.notify(f"Hata: {str(e)}")
				self.prompt_entered = False
				self.response_generated = False

		with self.db.last_prompt_container:
			threading.Thread(target=_generate, daemon=True).start()
		self._load_chat_list()

	def start_new_chat(self):
		"""Thread-safe chat oluşturma (callback yerine doğrudan queue sonucunu bekler)."""
		response_queue = queue.Queue()  # Sonucu taşımak için geçici queue

		def _db_task(c, user_ip):
			try:
				timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
				c.execute("INSERT INTO chats (timestamp, user_ip) VALUES (?, ?)", (timestamp, user_ip))
				chat_id = c.lastrowid
				response_queue.put(chat_id)  # Sonucu queue'ya koy
				return chat_id
			except Exception as e:
				response_queue.put(None)
				raise e

		# DB işlemini queue'ya ekle (self.db.queue kullanın)
		self.db.queue.put((_db_task, (self.user_ip,), {'callback': self._schedule_history_refresh}))  # Callback OLMADAN olur mu

		# Sonucu bekleyelim (timeout: 10 saniye)
		try:
			chat_id = response_queue.get(timeout=10.0)
			if chat_id is None:
				raise RuntimeError("Chat oluşturulamadı!")

			self.current_chat_id = chat_id
			with self.db.last_prompt_container:
				ui.notify(f"Yeni sohbet #{chat_id} başlatıldı")
			return chat_id
		except queue.Empty:
			raise RuntimeError("Chat oluşturma işlemi zaman aşımına uğradı!")

	def delete_chat(self, chat_id, callback=None):
		"""Belirtilen chat'i siler."""
		if chat_id:
			with self.history_container:
				self.db.delete_chat(chat_id, callback=self._schedule_history_refresh)
			if self.current_chat_id == chat_id:
				self.current_chat_id = None

	def _schedule_history_refresh(self, _=None):
		self._load_chat_list()
		self._refresh_history()

	def _update_history(self, chat_list):
		"""Refresh the chat history in the UI."""
		# Clear the history container
		self.history_container.clear()

		# Find the selected chat
		selected_chat = None
		for chat in chat_list:
			if chat["chat"][0] == self.current_chat_id:
				selected_chat = chat
				break

		if not selected_chat:
			return

		# Add rows for each prompt and response in the selected chat
		with self.history_container:
			for prompt in selected_chat["prompts"]:
				# Display the prompt
				with ui.row().classes("w-full p-2 bg-gray-100 border-b"):
					ui.label("Prompt:").classes("font-bold w-1/6")
					ui.label(prompt[3]).classes("w-5/6")  # Prompt text

				# Display the response
				with ui.row().classes("w-full p-2 bg-gray-50 border-b"):
					ui.label("Yanıt:").classes("font-bold w-1/6")
					ui.label(prompt[4]).classes("w-5/6")  # Response text

	def _update_chat_list(self, chat_list):
		"""Update the chat list UI in the main thread"""
		# Clear the existing chat list
		self.db.chat_list_container.clear()

		# Add each chat to the sidebar
		for chat in chat_list:
			chat_id = chat["chat"][0]
			timestamp = chat["chat"][1]
			with self.db.chat_list_container:
				with ui.row().classes("w-full items-center p-2 box-border"):
					# Chat load button
					ui.button(
						f"Chat {chat_id} - {timestamp}",
						on_click=lambda chat_id=chat_id: self._switch_chat(chat_id)
					).classes("flex-grow p-2 box-border")

					# Delete button
					ui.button(
						"❌",  # Delete icon
						on_click=lambda chat_id=chat_id: self.delete_chat(chat_id)
					).classes("p-2 box-border")

	def _refresh_history(self):
		def update_history(chat_list):
			self.history_container.clear()
			selected_chat = next((c for c in chat_list if c["chat"][0] == self.current_chat_id), None)
			if selected_chat:
				with self.history_container:
					for prompt in selected_chat["prompts"]:
						with ui.row().classes("w-full p-2 bg-gray-100 border-b"):
							ui.label("Prompt:").classes("font-bold w-1/6")
							ui.label(prompt[3]).classes("w-5/6")
						with ui.row().classes("w-full p-2 bg-gray-50 border-b"):
							ui.label("Yanıt:").classes("font-bold w-1/6")
							ui.label(prompt[4]).classes("w-5/6")

		self.db.get_chats(self.user_ip, callback=update_history)

	def _load_chat_list(self):
		"""Load the list of chats into the sidebar."""
		def update_chat_list(chat_list):
			# Clear the existing chat list
			self.db.chat_list_container.clear()

			# Add each chat to the sidebar
			for chat in chat_list:
				chat_id = chat["chat"][0]
				timestamp = chat["chat"][1]
				with self.db.chat_list_container:
					with ui.row().classes("w-full items-center p-2 box-border"):
						# Chat load button
						ui.button(
							f"Chat {chat_id} - {timestamp}",
							on_click=lambda chat_id=chat_id: self._switch_chat(chat_id)
						).classes("flex-grow p-2 box-border")

						# Delete button
						ui.button(
							"❌",  # Delete icon
							on_click=lambda chat_id=chat_id: self.delete_chat(chat_id)
						).classes("p-2 box-border")

		# Fetch the chat history and update the sidebar
		with self.db.chat_list_container:
			self.db.get_chats(self.user_ip, callback=self._update_chat_list)

	def _switch_chat(self, chat_id):
		"""Switch to the selected chat and load its history."""
		self.current_chat_id = chat_id
		self._refresh_history()  # Refresh the history to show the selected chat

	def log_cpu_temperature(self):
		while True:
			temp = self.get_cpu_temperature()
			print(f"CPU Sıcaklığı: {temp}")
			time.sleep(300)  # 5 dakikada bir

	def load_file(self, e):
		try:
			# NiceGUI'nin yeni sürümlerinde dosya bilgileri farklı şekilde geliyor
			if not hasattr(e, 'files') or not e.files:
				with self.db.last_prompt_container:
					ui.notify("Dosya seçilmedi!")
				return

			# İlk dosyayı al
			uploaded_file = e.files[0]

			# Dosya adı ve uzantısı
			file_name = uploaded_file.name
			file_extension = os.path.splitext(file_name)[1].lower()

			# Dosya içeriğini işle
			if file_extension in [".txt", ".py", ".js", ".css", ".sh", ".bat", ".md"]:
				self.reference_text = uploaded_file.read().decode('utf-8')
			elif file_extension == ".pdf":
				# PDF gibi binary dosyalar için geçici dosya oluştur
				with tempfile.NamedTemporaryFile(delete=False) as tmp:
					tmp.write(uploaded_file.read())
					tmp_path = tmp.name
				self.reference_text = read_pdf(tmp_path)
				os.unlink(tmp_path)
			elif file_extension == ".docx":
				with tempfile.NamedTemporaryFile(delete=False) as tmp:
					tmp.write(uploaded_file.read())
					tmp_path = tmp.name
				self.reference_text = read_docx(tmp_path)
				os.unlink(tmp_path)
			elif file_extension == ".html":
				self.reference_text = uploaded_file.read().decode('utf-8')
			else:
				with self.db.last_prompt_container:
					ui.notify("Desteklenmeyen dosya biçimi!")
				return

			with self.db.last_prompt_container:
				ui.notify(f"Dosya yüklendi: {file_name}")

		except Exception as ex:
			with self.db.last_prompt_container:
				ui.notify(f"Dosya işleme hatası: {str(ex)}")

	@staticmethod
	def get_cpu_temperature():
		try:
			temps = psutil.sensors_temperatures()
			if not temps:
				return "Sıcaklık bilgisi alınamadı"
			for name, entries in temps.items():
				for entry in entries:
					if "core" in entry.label.lower():
						return f"{entry.current}°C"
			return "Sıcaklık bilgisi alınamadı"
		except Exception as e:
			return f"Hata: {str(e)}"

# ----------------------------
# UYGULAMAYI BAŞLAT
# ----------------------------
def main():
	parser = argparse.ArgumentParser(description="GPT-Neo GUI Application")
	parser.add_argument("--port", "-p", type=int, default=1919, help="Port number to run the application on")
	parser.add_argument("--password", "-pw", type=str, default="letmein", help="Password to access the application")
	args = parser.parse_args()

	PORT = args.port
	PASSWORD = args.password  # Şifre parametresi

	# TasteModelApp örneği oluştur
	app_instance = TasteModelApp()
	app_instance.db = ChatHistoryDB()

	# Şifre doğrulama durumu
	password_verified = False

	# Kullanıcının IP adresini almak için bir sayfa oluştur
	@ui.page("/")
	def index(request: Request):
		nonlocal password_verified

		# Kullanıcının IP adresini al
		client_host = request.client.host

		# Kullanıcı oturumuna IP adresini kaydet
		if 'ip' not in app.storage.user:
			app.storage.user['ip'] = client_host

		# TasteModelApp örneğine IP adresini kaydet
		app_instance.user_ip = client_host

		# Kullanıcıya bildirim göster
		ui.notify(f"IP adresiniz kaydedildi: {client_host}")

		# Şifre doğrulanmamışsa şifre giriş ekranı göster
		if not password_verified:
			with ui.column().classes("w-full max-w-4xl mx-auto"):
				ui.label("Lütfen şifreyi girin:")
				password_input = ui.input(password=True)
				ui.button("Giriş Yap", on_click=lambda: check_password(password_input.value))

			return

		# Model yüklenene kadar yükleme ekranı göster
		if not app_instance.model_loaded:
			with ui.column().classes("w-full max-w-4xl mx-auto"):
				ui.spinner(size="lg")  # Yükleme spinner'ı
				ui.label("Model yükleniyor, lütfen bekleyin...")  # Yükleme mesajı

			# Use a timer to check if the model is loaded
			def check_model_loaded():
				if app_instance.model_loaded:
					ui.navigate.to("/")  # Reload the current page

			ui.timer(1.0, check_model_loaded)  # Check every second
			return

		# Ana UI bileşenlerini döndür
		return main_ui()

	# Şifre doğrulama fonksiyonu
	def check_password(password):
		nonlocal password_verified
		if password == PASSWORD:
			password_verified = True
			ui.notify("Şifre doğru! Ana sayfaya yönlendiriliyorsunuz...")
			ui.navigate.to("/")  # Ana sayfaya yönlendir
		else:
			ui.notify("Yanlış şifre! Lütfen tekrar deneyin.")

	# Ana UI bileşenlerini oluştur
	def main_ui():
		with ui.row().classes("w-full h-screen p-0 m-0 nowrap box-border"):
			# Sidebar for chat list (left side)
			with ui.column().classes("w-2/12 bg-gray-100 h-full overflow-y-auto p-0 m-0 box-border"):
				ui.button("Yeni Chat", on_click=app_instance.start_new_chat).classes("w-full p-2 box-border")
				app_instance.db.chat_list_container = ui.column().classes("w-full p-2 box-border")  # Container for chat list

			# Main interface (right side)
			with ui.column().classes("w-9/12 h-13/15 overflow-y-auto p-0 m-0 box-border"):
				# Model Parametreleri
				with ui.row().classes("w-full p-2 box-border"):
					ui.label("Max Token:").classes("w-1/8 box-border")
					app_instance.max_tokens = ui.input(value="300").classes("w-3/8 box-border")
					ui.label("Temperature:").classes("w-1/8 box-border")
					app_instance.temperature = ui.input(value="0.75").classes("w-3/8 box-border")

				# Sohbet Geçmişi
				app_instance.history_container = ui.column().classes("w-full p-2 box-border")  # Initialize history container

				# Yanıt Gösterme Alanı (for typewriter effect)
				app_instance.db.last_prompt_container = ui.column().classes("w-full p-2 box-border")
				with app_instance.db.last_prompt_container:
					with ui.row().classes("w-full p-2 bg-gray-100 border-b"):
						app_instance.prompt_label = ui.label().classes("font-bold w-1/6")
						app_instance.prompt_display = ui.label().classes("w-5/6")
					with ui.row().classes("w-full p-2 bg-gray-100 border-b"):
						app_instance.response_label = ui.label().classes("font-bold w-1/6")
						app_instance.response_display = ui.label().classes("w-5/6")  # response_display özelliğini başlatın

				# Prompt Giriş Alanı
				app_instance.prompt_entry = ui.textarea(label="Prompt").classes("w-full p-2 box-border")

				# Dosya Yükleme
				ui.upload(on_upload=app_instance.load_file).classes("w-full p-0 box-border")

				# Butonlar
				with ui.row().classes("w-full p-0 nowrap box-border"):
					with ui.row().classes("w-full p-0 nowrap box-border"):
						# Gönder Butonu
						ui.button(
							"Gönder",
							on_click=lambda: (
								threading.Thread(target=app_instance.generate_response, daemon=True).start()
							)
						).classes("flex-grow p-2 box-border").bind_enabled_from(
							app_instance, "model_loaded"  # Model yüklenene kadar buton pasif
						)
						# Geçmişi Sil Butonu
						ui.button(
							"❌",
							on_click=lambda: app_instance.delete_chat(app_instance.current_chat_id)
						).classes("p-2 box-border")

		# Load the chat list into the sidebar
		app_instance.db.get_chats(app_instance.user_ip, callback=app_instance._update_chat_list)

	# Uygulamayı belirtilen portta başlat ve stabil WebSocket ayarları ekle
	ui.run(
		port=PORT,
		storage_secret=PASSWORD,
		reconnect_timeout=9999,  # Daha uzun bir yeniden bağlanma süresi
		reload=False,  # Uygulamanın yeniden başlatılmasını engeller
		lifespan="on"  # Lifespan event handler'ı ekleyin
	)

if __name__ in {"__main__", "__mp_main__"}:
	main()
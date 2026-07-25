"""
Integración de Telegram para AI Platform.

Soporta:
- Mensajes de texto, archivos adjuntos (document, photo, audio, video)
- Notas de voz -> transcripción por OpenAI Whisper
- Documentos (PDF, DOCX, XLSX) -> analisis por Odin
- Imagenes con caption

Configuración:
- TELEGRAM_BOT_TOKEN: Token del bot desde @BotFather
- TELEGRAM_WEBHOOK_SECRET: Secret token para validar webhooks
"""

import asyncio
import io
import logging
import os
import tempfile
from typing import Any

import httpx
from openai import AsyncOpenAI

from ai_platform.channels.base import BaseChannel
from ai_platform.core.config import get_settings

logger = logging.getLogger(__name__)


class TelegramChannel(BaseChannel):
    """
    Handler de canal para Telegram.

    Soporta texto, archivos adjuntos, notas de voz con transcripcion,
    imagenes y videos.
    """

    channel = "telegram"

    def __init__(
        self,
        token: str | None = None,
        webhook_secret: str | None = None,
    ):
        self.settings = get_settings()
        self.token = token if token is not None else self.settings.TELEGRAM_BOT_TOKEN
        self.webhook_secret = webhook_secret if webhook_secret is not None else self.settings.TELEGRAM_WEBHOOK_SECRET
        self.base_url = f"https://api.telegram.org/bot{self.token}" if self.token else ""

    # =========================================================================
    # Webhook validation
    # =========================================================================

    async def validate_webhook(self, payload: Any, headers: dict | None = None) -> dict:
        if not isinstance(payload, dict):
            logger.warning("Payload de Telegram no es un dict")
            return {"valid": False, "reason": "payload_no_es_dict"}

        if headers and self.webhook_secret:
            secret_token = headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if secret_token and secret_token != self.webhook_secret:
                logger.warning("X-Telegram-Bot-Api-Secret-Token no coincide")
                return {"valid": False, "reason": "secret_token_no_coincide"}

        update_id = payload.get("update_id")
        if not update_id:
            logger.warning("Update sin update_id")
            return {"valid": False, "reason": "sin_update_id"}

        message = payload.get("message") or payload.get("edited_message") or payload.get("channel_post")
        if message:
            is_bot = message.get("from", {}).get("is_bot")
            if is_bot:
                logger.info("Ignorando mensaje de bot")
                return {"valid": False, "reason": "mensaje_de_bot"}

        return {"valid": True, "reason": "webhook_valido"}

    # =========================================================================
    # Message extraction (with attachments)
    # =========================================================================

    async def extract_message(self, raw_payload: Any) -> dict[str, Any]:
        if not isinstance(raw_payload, dict):
            return {
                "user_id": "",
                "user_name": "",
                "message_text": "",
                "chat_id": "",
                "attachments": [],
            }

        message = raw_payload.get("message") or raw_payload.get("edited_message") or raw_payload.get("channel_post")
        if not message:
            return {
                "user_id": "",
                "user_name": "",
                "message_text": "",
                "chat_id": "",
                "attachments": [],
            }

        user_info = message.get("from", {})
        user_id = str(user_info.get("id", ""))
        first_name = user_info.get("first_name", "")
        username = user_info.get("username", "")
        user_name = first_name or username or "Usuario"

        chat_info = message.get("chat", {})
        chat_id = str(chat_info.get("id", ""))

        message_text = message.get("text", "") or message.get("caption", "")

        attachments = self._collect_attachments(message)

        # Si hay archivos adjuntos, priorizar su procesamiento
        file_info = ""
        for att in attachments:
            file_type = att.get("type")
            file_name = att.get("file_name", "")
            caption = att.get("caption", "")
            if file_type == "voice":
                file_info += f"[Nota de voz: {att['duration']}s] "
                if caption:
                    file_info += f"Caption: {caption}\n"
            elif file_type == "audio":
                file_info += f"[Audio: {file_name}, {att['duration']}s, {att.get('performer', '')} - {att.get('title', '')}] "
                if caption:
                    file_info += f"Caption: {caption}\n"
            elif file_type in ("document",):
                mime = att.get("mime_type", "")
                file_info += f"[Documento: {file_name}, {mime}] "
                if caption:
                    file_info += f"Caption: {caption}\n"
            elif file_type == "photo":
                w = att.get("width", "")
                h = att.get("height", "")
                file_info += f"[Imagen: {w}x{h}] "
                if caption:
                    file_info += f"Caption: {caption}\n"
            elif file_type == "video":
                w = att.get("width", "")
                h = att.get("height", "")
                file_info += f"[Video: {w}x{h}, {att['duration']}s] "
                if caption:
                    file_info += f"Caption: {caption}\n"

        combined_text = message_text
        if file_info and file_info.strip():
            combined_text = f"{file_info}\n{message_text}".strip()

        return {
            "user_id": user_id,
            "user_name": user_name,
            "message_text": combined_text,
            "chat_id": chat_id,
            "attachments": attachments,
            "file_count": len(attachments),
        }

    def _collect_attachments(self, message: dict) -> list[dict]:
        """Extraer todos los archivos adjuntos del mensaje de Telegram."""
        attachments = []

        # Voice note
        voice = message.get("voice")
        if voice:
            attachments.append({
                "type": "voice",
                "file_id": voice.get("file_id"),
                "file_unique_id": voice.get("file_unique_id"),
                "mime_type": "audio/ogg",
                "file_name": "voice_note.ogg",
                "duration": voice.get("duration", 0),
                "file_size": voice.get("file_size"),
                "caption": message.get("caption", ""),
            })

        # Audio (song / audio file)
        audio = message.get("audio")
        if audio:
            ext = self._guess_extension(audio.get("mime_type", "audio/mpeg"), "mp3")
            attachments.append({
                "type": "audio",
                "file_id": audio.get("file_id"),
                "file_unique_id": audio.get("file_unique_id"),
                "mime_type": audio.get("mime_type", "audio/mpeg"),
                "file_name": f"{audio.get('title', 'audio')}.{ext}" if audio.get("title") else f"audio.{ext}",
                "duration": audio.get("duration", 0),
                "performer": audio.get("performer"),
                "title": audio.get("title"),
                "file_size": audio.get("file_size"),
                "caption": message.get("caption", ""),
            })

        # Document (PDF, DOCX, XLSX, code, etc.)
        document = message.get("document")
        if document:
            mime = document.get("mime_type", "")
            ext = self._guess_extension(mime, "bin")
            file_name = document.get("file_name")
            if not file_name:
                file_name = f"document.{ext}"
            elif not file_name.endswith(f".{ext}"):
                file_name = f"{ext[:5] or 'file'}.{ext}"
            attachments.append({
                "type": "document",
                "file_id": document.get("file_id"),
                "file_unique_id": document.get("file_unique_id"),
                "mime_type": mime,
                "file_name": file_name,
                "file_extension": ext,
                "file_size": document.get("file_size"),
                "caption": message.get("caption", ""),
            })

        # Photo (take highest resolution)
        photos = message.get("photo", [])
        if photos:
            photo = photos[-1]
            attachments.append({
                "type": "photo",
                "file_id": photo.get("file_id"),
                "file_unique_id": photo.get("file_unique_id"),
                "mime_type": "image/jpeg",
                "file_name": "photo.jpg",
                "width": photo.get("width"),
                "height": photo.get("height"),
                "caption": message.get("caption", ""),
            })

        # Video
        video = message.get("video")
        if video:
            ext = self._guess_extension(video.get("mime_type", "video/mp4"), "mp4")
            attachments.append({
                "type": "video",
                "file_id": video.get("file_id"),
                "file_unique_id": video.get("file_unique_id"),
                "mime_type": video.get("mime_type", "video/mp4"),
                "file_name": f"video.{ext}",
                "duration": video.get("duration", 0),
                "width": video.get("width"),
                "height": video.get("height"),
                "file_size": video.get("file_size"),
                "caption": message.get("caption", ""),
            })

        # Video note (burst message)
        video_note = message.get("video_note")
        if video_note:
            attachments.append({
                "type": "video_note",
                "file_id": video_note.get("file_id"),
                "file_unique_id": video_note.get("file_unique_id"),
                "mime_type": "video/mp4",
                "file_name": "circle_video.mp4",
                "length": video_note.get("length", 0),
                "file_size": video_note.get("file_size"),
            })

        # Animation/GIF
        animation = message.get("animation")
        if animation:
            mime = animation.get("mime_type", "image/gif")
            ext = self._guess_extension(mime, "mp4")
            attachments.append({
                "type": "animation",
                "file_id": animation.get("file_id"),
                "file_unique_id": animation.get("file_unique_id"),
                "mime_type": mime,
                "file_name": f"animation.{ext}",
                "duration": animation.get("duration", 0),
                "width": animation.get("width", 0),
                "height": animation.get("height", 0),
                "file_size": animation.get("file_size"),
            })

        return attachments

    @staticmethod
    def _guess_extension(mime_type: str, default_ext: str) -> str:
        """Guess file extension from MIME type."""
        mapping = {
            "application/pdf": "pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
            "application/msword": "doc",
            "text/plain": "txt",
            "text/csv": "csv",
            "text/html": "html",
            "text/markdown": "md",
            "text/json": "json",
            "text/xml": "xml",
            "text/yaml": "yaml",
            "text/rtf": "rtf",
            "application/rtf": "rtf",
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/webp": "webp",
            "image/gif": "gif",
            "image/tiff": "tiff",
            "image/bmp": "bmp",
            "image/svg+xml": "svg",
            "audio/mpeg": "mp3",
            "audio/ogg": "ogg",
            "audio/wave": "wav",
            "audio/webm": "webm",
            "audio/mp4": "m4a",
            "audio/aac": "aac",
            "video/mp4": "mp4",
            "video/webm": "webm",
            "video/ogg": "ogv",
            "video/x-matroska": "mkv",
        }
        return mapping.get(mime_type, default_ext)

    # =========================================================================
    # File download
    # =========================================================================

    async def download_file(self, file_id: str) -> tuple[bytes, str]:
        """Download a file from Telegram API.

        Args:
            file_id: Telegram file ID

        Returns:
            (file_bytes, mime_type)
        """
        if not file_id or not self.token:
            raise ValueError("File ID y token son requeridos")

        url = f"{self.base_url}/getFile"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json={"file_id": file_id})
                response.raise_for_status()
                data = response.json()

                if not data.get("ok"):
                    error_desc = data.get("description", "File not found")
                    raise ValueError(f"Telegram API error: {error_desc}")

                file_path = data["result"].get("file_path")
                if not file_path:
                    raise ValueError("No file_path returned from getFile")

                file_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"

                async with httpx.AsyncClient(timeout=60.0) as client:
                    file_response = await client.get(file_url)
                    file_response.raise_for_status()
                    file_bytes = file_response.content

                    content_type = file_response.headers.get(
                        "content-type", "application/octet-stream"
                    )

                    logger.info(
                        f"Archivo descargado: {file_id}, "
                        f"{len(file_bytes):,} bytes, mime={content_type}"
                    )
                    return file_bytes, content_type

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error descargando archivo {file_id}: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error descargando archivo {file_id}: {e}")
            raise

    async def download_file_to_temp(self, file_id: str) -> str:
        """Download a file to a temporary file and return the path.

        Useful for passing the file to Whisper transcription.

        Args:
            file_id: Telegram file ID

        Returns:
            Path to the temporary file
        """
        file_bytes, _ = await self.download_file(file_id)

        temp_dir = os.environ.get("TEMP", os.environ.get("TMP", "/tmp"))
        fd = tempfile.NamedTemporaryFile(
            dir=temp_dir, delete=False, suffix=".audio"
        )
        fd.write(file_bytes)
        fd.close()
        logger.info(f"Archivo temporal creado: {fd.name}")
        return fd.name

    # =========================================================================
    # Voice transcription (OpenAI Whisper)
    # =========================================================================

    async def transcribe_voice(self, audio_path: str, mime_type: str = "audio/webm") -> str:
        """Transcribe a voice note using OpenAI's Whisper API.

        Args:
            audio_path: Path to the audio file (supports WebM/OGG for voice notes)
            mime_type: MIME type of the audio file

        Returns:
            Transcribed text or error message
        """
        try:
            client = AsyncOpenAI(base_url=self.settings.NAN_API_URL, api_key=self.settings.NAN_API_KEY)

            with open(audio_path, "rb") as f:
                response = await client.audio.transcriptions.create(
                    model="whisper",
                    file=f,
                    language="es",
                )

            transcript = response.text.strip()
            logger.info(f"Transcripcion completada: {len(transcript)} chars")
            return transcript

        except Exception as e:
            logger.error(f"Error transcribiendo audio: {e}")
            return f"[No se pudo transcribir el audio. Error: {e}]"

    async def process_attachments(self, attachments: list[dict], chat_id: str, reply_to_message_id: int | None = None) -> list[dict]:
        """Process all attachments from a message.

        Downloads files, transcribes voice notes, extracts text from documents.
        Does NOT send any messages to the user — silent processing only.

        Returns:
            List of processed file info dicts with transcriptions and extracted_text
        """
        if not attachments:
            return []

        results = []
        for att in attachments:
            att_type = att.get("type")
            file_id = att.get("file_id")

            if not file_id:
                results.append({"type": att_type, "file_id": file_id, "error": "No file_id"})
                continue

            try:
                if att_type == "voice":
                    temp_path = await self.download_file_to_temp(file_id)
                    try:
                        transcript = await self.transcribe_voice(temp_path, att.get("mime_type", "audio/ogg"))
                        results.append({
                            "type": "voice",
                            "file_id": file_id,
                            "file_name": "voice_note.ogg",
                            "duration": att.get("duration", 0),
                            "transcription": transcript,
                            "caption": att.get("caption", ""),
                            "temp_path": temp_path,
                        })
                    except Exception as e:
                        results.append({"type": "voice", "file_id": file_id, "error": str(e)})
                    finally:
                        try:
                            os.unlink(temp_path)
                        except Exception:
                            pass

                elif att_type == "document":
                    temp_path = await self.download_file_to_temp_with_ext(file_id, att.get("file_extension", "bin"))
                    try:
                        extracted_text = await self._extract_document_text(temp_path, att.get("mime_type", ""))
                        results.append({
                            "type": "document",
                            "file_id": file_id,
                            "file_name": att.get("file_name"),
                            "file_extension": att.get("file_extension", "bin"),
                            "mime_type": att.get("mime_type", ""),
                            "caption": att.get("caption", ""),
                            "temp_path": temp_path,
                            "extracted_text": extracted_text,
                        })
                    except Exception as e:
                        results.append({"type": "document", "file_id": file_id, "error": str(e)})

                elif att_type == "photo":
                    results.append({"type": "photo", "file_id": file_id, "caption": att.get("caption", "")})

                elif att_type == "audio":
                    results.append({"type": "audio", "file_id": file_id, "title": att.get("title")})

                elif att_type == "video":
                    results.append({"type": "video", "file_id": file_id})

                elif att_type == "video_note":
                    results.append({"type": "video_note", "file_id": file_id})

                elif att_type == "animation":
                    results.append({"type": "animation", "file_id": file_id})

            except Exception as e:
                logger.error(f"Error procesando archivo {att_type}: {e}")
                results.append({"type": att_type, "file_id": file_id, "error": str(e)})

        return results

    async def _extract_document_text(self, file_path: str, mime_type: str) -> str:
        """Extract text from a document file.

        Supports: PDF, DOCX, XLSX, TXT, CSV, plain text files.
        Uses the same libraries as the document pipeline.
        """
        extracted = ""

        try:
            if mime_type == "application/pdf":
                try:
                    import pdfplumber
                    with pdfplumber.open(file_path) as pdf:
                        pages_text = []
                        for page in pdf.pages:
                            text = page.extract_text()
                            if text:
                                pages_text.append(text)
                        extracted = "\n\n".join(pages_text)
                except ImportError:
                    import PyMuPDF
                    doc = PyMuPDF.open(file_path)
                    pages_text = []
                    for page in doc:
                        text = page.get_text()
                        if text.strip():
                            pages_text.append(text.strip())
                    extracted = "\n\n".join(pages_text)

            elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                from docx import Document
                docx_obj = Document(file_path)
                extracted = "\n".join(para.text for para in docx_obj.paragraphs)

            elif (
                mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                or "ms-excel" in mime_type
            ):
                import openpyxl
                wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
                sheet_text = []
                for ws in wb.worksheets:
                    sheet_text.append(f"--- Sheet: {ws.title} ---")
                    for row in ws.iter_rows(values_only=True):
                        row_str = " | ".join(str(cell) if cell is not None else "" for cell in row)
                        if row_str.strip():
                            sheet_text.append(row_str)
                    wb.close()
                extracted = "\n".join(sheet_text)

            elif mime_type == "text/plain":
                extracted = open(file_path, "r", encoding="utf-8").read()

            elif mime_type == "text/csv":
                content = open(file_path, "r", encoding="utf-8").read()
                extracted = "CSV:\n" + content

            elif mime_type in ("text/html", "text/markdown", "text/xml", "text/json", "text/yaml"):
                extracted = open(file_path, "r", encoding="utf-8").read()

        except Exception as e:
            logger.warning(f"Error extrayendo texto de documento: {e}")
            extracted = "[No se pudo extraer el texto del documento]"

        return extracted if extracted else ""

    async def _reply_processing(self, chat_id: str, reply_to: int | None, text: str):
        """Send a quick processing indicator reply."""
        await self.send_message(
            chat_id=chat_id,
            text=text,
            reply_to_message_id=reply_to,
        )

    async def download_file_to_temp_with_ext(self, file_id: str, ext: str) -> str:
        """Download a file to a temporary file with a specific extension."""
        file_bytes, _ = await self.download_file(file_id)

        temp_dir = os.environ.get("TEMP", os.environ.get("TMP", "/tmp"))
        fd = tempfile.NamedTemporaryFile(
            dir=temp_dir, delete=False, suffix=f".{ext}"
        )
        fd.write(file_bytes)
        fd.close()
        logger.info(f"Archivo temporal: {fd.name} ({ext})")
        return fd.name

    async def send_file(self, chat_id: str, file_path: str, file_name: str, mime_type: str = "application/octet-stream", parse_mode: str = "HTML", reply_to_message_id: int | None = None) -> Any:
        """Send a file from a local path.

        Args:
            chat_id: Telegram chat ID
            file_path: Local path to the file
            file_name: Display name / caption
            mime_type: MIME type for the file
            parse_mode: Parse mode (unused for file send)
            reply_to_message_id: Message ID to reply to

        Returns:
            Telegram API response or error dict
        """
        if not self.token or not chat_id:
            return {"status": "error", "message": "Missing token or chat_id"}

        try:
            with open(file_path, "rb") as f:
                if mime_type == "application/pdf":
                    endpoint = "/sendDocument"
                elif mime_type.startswith("image/"):
                    endpoint = "/sendPhoto"
                elif mime_type.startswith("video/"):
                    endpoint = "/sendVideo"
                elif mime_type.startswith("audio/"):
                    endpoint = "/sendAudio"
                else:
                    endpoint = "/sendDocument"

                url = f"{self.base_url}{endpoint}"

                files = {"" if endpoint == "/sendPhoto" else "document": (file_name, f, mime_type)}
                data = {"chat_id": chat_id, "caption": file_name}

                if reply_to_message_id:
                    data["reply_to_message_id"] = reply_to_message_id

                last_error = None
                for attempt in range(3):
                    try:
                        async with httpx.AsyncClient(timeout=60.0) as client:
                            response = await client.post(url, files=files, data=data)
                            response.raise_for_status()
                            data = response.json()
                            if data.get("ok"):
                                logger.info(f"Archivo enviado: {file_name} to {chat_id}")
                                return data
                    except Exception as e:
                        last_error = e
                        logger.warning(f"Error enviando archivo (intento {attempt+1}): {e}")
                        await asyncio.sleep(2 ** attempt)

                logger.error(f"Error enviando archivo tras 3 intentos: {last_error}")
                return {"status": "error", "message": str(last_error)}

        except FileNotFoundError:
            return {"status": "error", "message": f"Archivo no encontrado: {file_path}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # =========================================================================
    # Existing methods (keep unchanged)
    # =========================================================================

    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: dict | None = None,
        reply_to_message_id: int | None = None,
    ) -> Any:
        if not self.token:
            logger.error("No se puede enviar mensaje: TELEGRAM_BOT_TOKEN no configurado")
            return {"status": "error", "message": "Bot token no configurado"}

        if not chat_id:
            logger.error("No se puede enviar mensaje: chat_id vacío")
            return {"status": "error", "message": "chat_id no proporcionado"}

        url = f"{self.base_url}/sendMessage"

        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }

        if reply_markup:
            payload["reply_markup"] = reply_markup

        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id

        last_error = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                    data = response.json()

                    if data.get("ok"):
                        logger.info(f"Mensaje enviado a Telegram chat_id={chat_id}")
                        return data
                    else:
                        error_desc = data.get("description", "Error desconocido")
                        error_code = data.get("error_code")
                        if error_code == 429:
                            retry_after = data.get("retry_after", 5)
                            logger.warning(f"Rate limited por Telegram. Esperando {retry_after}s (intento {attempt+1}/3)")
                            await asyncio.sleep(retry_after)
                            continue
                        logger.error(f"Error enviando a Telegram: {error_desc}")
                        return {"status": "error", "message": error_desc}

            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code == 429:
                    try:
                        retry_after = e.response.json().get("retry_after", 5)
                    except Exception:
                        retry_after = 5
                    logger.warning(f"Rate limited HTTP. Esperando {retry_after}s (intento {attempt+1}/3)")
                    await asyncio.sleep(retry_after)
                    continue
                logger.error(f"HTTP error enviando mensaje a Telegram: {e.response.status_code} - {e.response.text}")
                return {"status": "error", "message": f"HTTP {e.response.status_code}"}
            except httpx.ReadTimeout:
                last_error = last_error or Exception("ReadTimeout")
                wait = 2 ** attempt
                logger.warning(f"Timeout en Telegram. Reintentando en {wait}s (intento {attempt+1}/3)")
                await asyncio.sleep(wait)
            except httpx.RequestError as e:
                last_error = e
                logger.warning(f"Error de red. Reintentando (intento {attempt+1}/3)")
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                last_error = e
                logger.warning(f"Error inesperado. Reintentando (intento {attempt+1}/3)")
                await asyncio.sleep(2 ** attempt)

        logger.error(f"Error enviando mensaje a Telegram tras 3 intentos: {last_error}")
        return {"status": "error", "message": f"Error tras 3 intentos: {last_error}"}

    async def send_answer(
        self,
        callback_query_id: str,
        text: str,
        show_alert: bool = False,
    ) -> Any:
        if not self.token:
            return {"status": "error", "message": "Bot token no configurado"}

        url = f"{self.base_url}/answerCallbackQuery"
        payload = {
            "callback_query_id": callback_query_id,
            "text": text,
            "show_alert": show_alert,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return data
        except Exception as e:
            logger.error(f"Error respondiendo callback query: {e}")
            return {"status": "error", "message": str(e)}

    def _chunk_message(self, text: str, max_length: int = 4096) -> list[str]:
        return super()._chunk_message(text, max_length=max_length)


def create_telegram_keyboard(buttons: list[list[str]], url: str | None = None) -> dict:
    keyboard = []
    for row in buttons:
        keyboard_row = []
        for label in row:
            if url:
                keyboard_row.append(
                    {
                        "text": label,
                        "url": url,
                    }
                )
            else:
                keyboard_row.append(
                    {
                        "text": label,
                        "callback_data": label,
                    }
                )
        keyboard.append(keyboard_row)

    return {
        "keyboard": keyboard,
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


REACTION_RATING_MAP: dict[str, int] = {
    "emoji_thumbs_up": 3,
    "emoji_thumbs_down": 1,
    "emoji_heart": 3,
    "emoji_fire": 3,
    "emoji_star": 3,
}


class TelegramReactionHandler:
    def __init__(self, bot_token: str | None = None):
        self.settings = get_settings()
        self.token = bot_token or self.settings.TELEGRAM_BOT_TOKEN
        self.base_url = f"https://api.telegram.org/bot{self.token}" if self.token else ""

    def handle_reaction(self, reaction: dict[str, Any]) -> dict[str, Any]:
        message = reaction.get("message", {})
        chat = message.get("chat", {})
        user = reaction.get("user", {})
        reaction_obj = reaction.get("reaction", [{}])[0] if reaction.get("reaction") else {}

        reaction_type = reaction_obj.get("type", {}).get("name", "") if reaction_obj.get("type") else ""
        rating = REACTION_RATING_MAP.get(reaction_type)

        if rating is None:
            return {"status": "ignored", "reaction": reaction_type}

        chat_id = str(chat.get("id", ""))
        user_id = str(user.get("id", ""))

        logger.info(f"Reaction feedback: user={user_id}, chat={chat_id}, reaction={reaction_type}, rating={rating}")

        return {
            "status": "recorded",
            "reaction": reaction_type,
            "rating": rating,
            "user_id": user_id,
            "chat_id": chat_id,
        }

    def handle_command(self, message_text: str, chat_id: str, user_id: str) -> dict[str, Any]:
        parts = message_text.strip().split()
        if not parts:
            return {"status": "ignored"}

        command = parts[0].lower()

        if command == "/rate":
            rating_str = parts[1].lower() if len(parts) > 1 else ""
            if rating_str in ("up", "\U0001f44d", "+"):
                return {
                    "status": "recorded",
                    "rating": 3,
                    "response": "Feedback registrado: \U0001f44d \u00a1Gracias!",
                }
            elif rating_str in ("down", "\U0001f44e", "-"):
                return {
                    "status": "recorded",
                    "rating": 1,
                    "response": "Feedback registrado: \U0001f44e Lo sentimos. Mejoremos.",
                }
            else:
                return {
                    "status": "recorded",
                    "rating": 2,
                    "response": "Usa: /rate up o /rate down para calificar respuestas de Odin.",
                }

        return {"status": "ignored"}

    async def download_photo(self, file_id: str) -> tuple[bytes, str]:
        """Descargar foto de Telegram y retornar como bytes."""
        photo_bytes, _ = await self.download_file(file_id)
        return photo_bytes, "image/jpeg"
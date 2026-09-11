# 🎵 YouTube Music Telegram Bot

Bot privado de Telegram para recibir una playlist de YouTube y obtener:
- audio solamente (no descarga el video)
- mejor audio disponible, prefiriendo M4A
- portada incrustada cuando FFmpeg puede hacerlo
- metadatos
- subtítulos oficiales y automáticos disponibles en los idiomas configurados
- subtítulos separados en SRT/VTT/etc.
- cancelación
- registro SQLite básico

## Importante

Úsalo únicamente con contenido que tengas derecho a descargar. Las condiciones de YouTube y los derechos de autor pueden limitar determinados usos.

Telegram limita actualmente los envíos de archivos de bots a 50 MB mediante la Bot API oficial. El bot deja un margen de seguridad de 49 MB.

## Instalación en un servidor Linux

1. Instala Docker.
2. Crea el bot con @BotFather y copia el token.
3. Averigua tu Telegram user ID.
4. Copia `.env.example` como `.env`.
5. Completa BOT_TOKEN y ALLOWED_USER_ID.
6. Ejecuta:

   docker compose up -d --build

7. Abre Telegram y manda `/start` al bot.

## Subtítulos

Por defecto busca:
- español: es.*
- inglés: en.*

Puedes cambiar `SUB_LANGS`, por ejemplo:

SUB_LANGS=es.*

o:

SUB_LANGS=es.*,ja.*

Los subtítulos se guardan como archivos separados. No se descarga el video para obtenerlos.

## Máxima calidad

El selector `m4a/bestaudio/best` intenta conservar el mejor audio disponible y evita una conversión innecesaria a MP3. La calidad final está limitada por la calidad que ofrezca la fuente.

## Seguridad

El bot acepta mensajes solamente del Telegram ID configurado en `ALLOWED_USER_ID`. Nunca compartas el token de BotFather.

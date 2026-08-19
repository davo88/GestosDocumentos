# Gestor de Documentos

Aplicacion web en Django para administrar proyectos, carpetas, documentos, tickets de revision y sincronizacion de archivos de texto o markdown con GitHub.

## Requisitos

- Python 3.13
- pip
- Git

## Instalacion

1. Clona el repositorio:

```bash
git clone https://github.com/davo88/GestosDocumentos.git
cd GestosDocumentos
```

2. Crea y activa un entorno virtual:

```bash
python -m venv .venv
```

PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

CMD:

```bat
.\.venv\Scripts\activate.bat
```

3. Instala dependencias:

```bash
pip install -r requirements.txt
```

4. Crea tu archivo de entorno:

```bash
copy .env.example .env
```

5. Aplica migraciones:

```bash
python manage.py migrate
```

6. Crea un superusuario:

```bash
python manage.py createsuperuser
```

7. Inicia el servidor:

```bash
python manage.py runserver
```

La aplicacion quedara disponible en `http://127.0.0.1:8000/`.

## Variables de entorno

El archivo `.env` usa estas variables:

```env
GITHUB_OWNER=TeenekTrust
GITHUB_REPO=Gestor-Documental
GITHUB_TOKEN=coloca_aqui_tu_token
```

## Que instala `requirements.txt`

- `Django`: framework principal.
- `python-dotenv`: carga variables desde `.env`.
- `python-docx`: lectura de archivos `.docx`.
- `lxml`: soporte XML usado por `python-docx`.
- `asgiref`, `sqlparse`, `typing_extensions`, `tzdata`: dependencias requeridas por el entorno actual.

## Notas

- La base de datos usada por defecto es SQLite (`db.sqlite3`).
- `.env`, `.venv`, `db.sqlite3` y `media/` no se suben al repositorio.
- Para que la sincronizacion con GitHub funcione, debes configurar un token valido en `GITHUB_TOKEN` o desde la configuracion del sistema dentro de la app.

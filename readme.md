# Ad Monitor

Ad Monitor — набор инструментов для записи радиоэфира, распознавания речи и поиска рекламных роликов. Результаты обработки сохраняются в SQLite, а веб-приложение показывает записи из базы.

## Возможности

- Запись интернет-радио по расписанию в MP3.
- Транскрибация аудио через Ollama с временными метками.
- Поиск рекламных фрагментов в транскрипции с помощью языковой модели Ollama.
- Нарезка найденных фрагментов и сохранение метаданных в SQLite.
- Расчёт Chromaprint-отпечатков аудиофрагментов.
- Экспорт объявлений в CSV.
- Flask-интерфейс и API для просмотра записей таблицы `radio_plays`.

## Требования

- Windows и Python 3.10 или новее.
- Ollama с доступной локальной моделью для распознавания речи и моделью для детектора рекламы.
- FFmpeg-библиотеки, необходимые PyAV для чтения и записи аудио.
- Для Chromaprint — исполняемый файл `fpcalc` в `PATH` либо доступная библиотека `libchromaprint`.

Модели Ollama, указанные в коде по умолчанию:

- ASR: `hf.co/foryoung365/Qwen3-ASR-1.7B-Q4_K_M-GGUF:Q4_K_M`
- Детектор рекламы: `gemma4:26b`

Перед обработкой убедитесь, что Ollama запущен и эти модели доступны (`ollama pull <имя-модели>` при необходимости).

## Установка

Из корня проекта в PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements
```

В репозитории файл зависимостей называется `requirements` (без расширения). Установите также `fpcalc`, если планируете рассчитывать аудиоотпечатки.

## Быстрый старт

### 1. Запись эфира

```powershell
.\.venv\Scripts\python.exe .\recorder\recorder.py `
  --stream-url "https://stream.autoradio.ru/autoradio" `
  --output-dir autoradio
```

Рекордер работает по расписанию ежедневно с 06:00 до 23:59. По умолчанию он записывает окна `14-21` и `44-51` каждой активной минуты часа. Формат — `НАЧАЛО-КОНЕЦ`, минуты внутри часа; несколько окон разделяются запятыми:

```powershell
.\.venv\Scripts\python.exe .\recorder\recorder.py --recording-windows 00-29,30-59
```

Записи создаются в `recorder/audio/<output-dir>/<YYYY-MM-DD>/<HH-MM-SS>.mp3`, журналы — в соседней папке `logs`.

### 2. Транскрибация

Обработать все записи станции за дату:

```powershell
.\.venv\Scripts\python.exe .\asr\asr_ollama.py --station autoradio --recording_date 2026-09-25
```

Обработать одну запись (время начала в формате `HH-MM-SS`):

```powershell
.\.venv\Scripts\python.exe .\asr\asr_ollama.py --station autoradio --recording_date 2026-09-25 --recording_time 14-14-00
```

По умолчанию аудио делится на чанки по 6 секунд с перекрытием 1 секунда. Параметры можно изменить через `--chunk-seconds` и `--overlap-seconds`. Транскрипции сохраняются в `asr/text/<station>/<date>/`.

### 3. Поиск рекламы

```powershell
.\.venv\Scripts\python.exe .\detector\adetector.py --station autoradio --recording_date 2026-09-25
```

Чтобы обработать только одну запись, добавьте `--recording_time 14-14-00`. Результаты сохраняются в JSON в `detector/text/<station>/<date>/`.

### 4. Нарезка и сохранение объявлений

```powershell
.\.venv\Scripts\python.exe .\labler\labler.py --station autoradio --recording_date 2026-09-25
```

Можно указать одну запись параметром `--recording_time`. Вырезанные рекламные фрагменты сохраняются в `labler/audio/<station>/<date>/`, а метаданные — в таблицу `advertisements` базы `radio.db`.

### 5. Веб-интерфейс

```powershell
.\.venv\Scripts\python.exe .\app.py
```

Откройте <http://127.0.0.1:5000>. Приложение создаёт таблицу `radio_plays` при запуске. API `GET /api/plays?date=YYYY-MM-DD&hour=0..23` возвращает записи за выбранный час; `POST /api/plays` добавляет запись с JSON-полями `date`, `time` и `title`.

### 6. Экспорт в CSV

```powershell
.\.venv\Scripts\python.exe .\export.py --output advertisements.csv
```

Относительный путь задаётся относительно каталога `data/`.

## Хранение данных

База данных — `radio.db` в корне проекта. Используются таблицы:

- `advertisements` — объявления, добавленные этапом разметки, с временными границами, описанием, уверенностью модели и путями к аудио.
- `audio_chunk_fingerprints` — Chromaprint-отпечатки обработанных чанков.
- `radio_plays` — записи, которые читает веб-интерфейс и API.

Скрипты ASR ищут исходные записи в `recorder/audio/<station>/<date>/`. Имена станций (`--station`) должны совпадать с именами каталогов, используемыми при записи.

**Примечание:** таблицы `advertisements` и `radio_plays` сейчас независимы: этап разметки записывает данные в `advertisements`, а веб-интерфейс читает `radio_plays`.

## Структура проекта

```text
app.py                  Flask-приложение и API
recorder/recorder.py    Запись радиоэфира
asr/asr_ollama.py       Транскрибация аудио и отпечатки чанков
asr/fingerprint.py      Работа с Chromaprint и SQLite
detector/adetector.py   Поиск рекламы в транскрипциях
labler/labler.py        Нарезка объявлений и сохранение метаданных
export.py               Экспорт объявлений в CSV
templates/              HTML-шаблоны
static/                 CSS и JavaScript веб-интерфейса
tests/                  Автотесты
radio.db                Локальная база SQLite
```

## Тесты

```powershell
.\.venv\Scripts\python.exe -m pytest
```

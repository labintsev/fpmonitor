# Ad monitor 

Система записи и идентификации рекламных роликов

## 1. Веб интерфейс

Фласк приложение для визуализации таблицы radio_plays из базы данных radio.db 

| Station | Date       | Start    | End      | Duration | Brand  |  Ad ID  |
| ------- | ---------- | -------- | -------- | -------: | ------ | ------ |
| Radio A | 2026-08-14 | 12:14:32 | 12:15:02 |      30s | Toyota |  001 |
| Radio A | 2026-08-14 | 12:37:11 | 12:37:41 |      30s | Lidl   |  002 |
| Radio A | 2026-08-14 | 12:51:04 | 12:51:34 |      30s | Toyota |  003 |


# 2. Архитектура

RADIO audio stream
    │
    ▼
[1] Audio recording
    │
    ▼
[2] Ollama Qwen ASR
    │
    ▼
[3] Ollama Ad identification 
    │
    ▼
[4] Database 
    │
    ▼
[5] Web UI


## 2.1 Audio recording

Скрипт recorder\recorder.py  

Файлы сохраняеются в папку по следующему шаблону: 

recorder\audio\autoradio\2026-08-17\Avto_99.9_0944_0951.mp3


## 2.2 ASR и цифровые отпечатки

`asr/asr_ollama.py` делит запись на чанки, строит для каждого чанка
Chromaprint через `pyacoustid` и сохраняет результат в SQLite `radio.db`, в
таблицу `audio_chunk_fingerprints`. Границы чанка и путь исходной записи входят
в уникальный ключ, поэтому повторная обработка обновляет существующую запись.

Для работы `pyacoustid` нужен backend Chromaprint: установите `fpcalc` и
добавьте его в `PATH` либо установите `libchromaprint` для активного Python
окружения. Сам пакет Python устанавливается из `reqirements`.


# 3. Usage

```
.\.venv\Scripts\python.exe .\recorder\recorder.py --stream-url https://radio-stream --output-dir radio-name 
```


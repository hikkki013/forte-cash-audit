# Контракт для интерфейса, v0.1

Base URL: `http://127.0.0.1:8000`. Все запросы, кроме `/health` и документации, требуют заголовок `X-API-Key`. Локальный ключ после запуска — в `runtime/api-key.txt`.

## Загрузка

`POST /api/v1/analyze`, `multipart/form-data`, поле `file`: MOV либо MP4, не более 200 МиБ.

Успех: HTTP 202, `{"job_id":"..."}`. Одна обработка одновременно, максимум два принятых задания (включая ожидающее). При заполнении очереди HTTP 429.

## Получение результата

`GET /api/v1/jobs/{job_id}`. Опрос раз в 1–2 сек. HTTP 200:

```json
{
  "job_id": "...",
  "status": "done",
  "result": {
    "verdict": "violation",
    "violations": [{
      "type": "cash_unattended",
      "timecode_sec": 10.0,
      "confirmed_at_sec": 13.0,
      "review_required": true,
      "description": "Описание наблюдения и ограничения...",
      "evidence_frames": [{"timestamp_sec": 10.0, "image_base64": "..."}]
    }],
    "warnings": ["..."],
    "meta": {
      "model": "grounding-dino-tiny",
      "enabled_rules": ["cash_unattended"],
      "sampled_frames": 20,
      "processing_sec": 11.34,
      "peak_gpu_mb": 1394.2
    }
  },
  "error": null
}
```

Пример сокращён; настоящий ответ с картинками — `outputs/api-smoke/response.json`.

- `processing`: `result=null`, `error=null`.
- `done`: результат доступен; `verdict` равен `violation` или `no_violation`.
- `failed`: `result=null`, `error` — текст/код. **Не показывать как «нарушений нет»**.
- `timecode_sec`: начало наблюдаемого условия. `confirmed_at_sec`: когда накопились условия правила.
- `peak_gpu_mb`: пик allocated-памяти PyTorch, не вся VRAM процесса. На CPU — null.
- Картинка: `src="data:image/jpeg;base64," + frame.image_base64`.
- В интерфейсе показывать «Требует проверки» и предупреждения. Для `no_violation`: «По проверяемым правилам событий не найдено».

Ошибки HTTP: 400 пустой файл, 401 ключ, 404 неизвестное/устаревшее задание, 408 копирование загрузки заняло слишком долго, 413 размер, 415 расширение, 429 очередь, 503 ключ сервера не настроен. Ошибка анализа/повреждённое видео возвращаются как `failed`, не обязательно HTTP 4xx.

## JavaScript

```javascript
export async function analyzeVideo(file, apiKey, onStatus = () => {}) {
  const base = 'http://127.0.0.1:8000';
  const headers = {'X-API-Key': apiKey};
  const body = new FormData();
  body.append('file', file);
  let response = await fetch(base + '/api/v1/analyze', {method: 'POST', headers, body});
  if (!response.ok) throw new Error(await response.text());
  const {job_id} = await response.json();
  const deadline = Date.now() + 300000;
  while (Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 1500));
    response = await fetch(base + '/api/v1/jobs/' + job_id, {headers});
    if (!response.ok) throw new Error(await response.text());
    const job = await response.json();
    onStatus(job.status);
    if (job.status === 'failed') throw new Error(job.error || 'Ошибка анализа');
    if (job.status === 'done') return job.result;
  }
  throw new Error('Не удалось дождаться результата');
}
```

Не устанавливать `Content-Type` вручную при отправке FormData. Не зашивать ключ в публичный frontend bundle; это локальная демонстрация для доверенных пользователей, не публичный сервис.

## Эксплуатационные границы

По умолчанию CORS разрешает `http://localhost:3000` и `http://localhost:5173`. Другой origin задаётся через `FORTE_CORS_ORIGINS` перед запуском. `127.0.0.1` и `localhost` в origin — разные значения.

На другом компьютере `127.0.0.1` указывает на тот компьютер, не на ноутбук автора. Для командной демонстрации сначала запустить интерфейс и backend на одном ноутбуке. Публичную публикацию и сетевой доступ не настраивали.

Бюджет обработки — 240 сек после приёма запроса, включая очередь, копирование и холодную загрузку модели. Проверки дедлайна кооперативные: зависший вызов GPU не прерывается принудительно. Это не строгая гарантия «любой файл менее 5 минут». Ограничение размера действует после разбора multipart; публичному серверу нужен внешний ingress-limit.

Хранится около 20 последних заданий; завершённые удаляются при обращениях спустя час. Всё хранится в памяти, без БД. Результат не сохраняется при перезапуске. Health сообщает доступность процесса и наличие файлов, **не качество модели и не готовность CUDA**.

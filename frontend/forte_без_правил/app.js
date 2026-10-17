/* ==========================================================
   Кассовый контроль — логика интерфейса
   Структура:
   1. Настройки
   2. Элементы страницы и состояние
   3. Вспомогательные функции
   4. Выбор файла
   5. Работа с API
   6. Справочник правил
   7. Отображение результата
   8. Обработчики событий
   ========================================================== */

/* ---------- 1. Настройки ---------- */
const CONFIG = {
  maxFileMb: 200,                 // соответствует лимиту API; ключ не хранится в JS
  pollIntervalMs: 2000,           // как часто спрашивать статус задачи
  timeoutMs: 5 * 60 * 1000,       // сколько ждать результат (по ТЗ — 5 минут)
};

/* ---------- 2. Элементы страницы и состояние ---------- */
const el = {
  dropzone: document.getElementById("dropzone"),
  fileInput: document.getElementById("fileInput"),
  fileName: document.getElementById("fileName"),
  preview: document.getElementById("preview"),
  startBtn: document.getElementById("startBtn"),
  resetBtn: document.getElementById("resetBtn"),
  progressBars: document.querySelectorAll("#progress i"),
  status: document.getElementById("status"),
  error: document.getElementById("error"),
  placeholder: document.getElementById("placeholder"),
  loader: document.getElementById("loader"),
  result: document.getElementById("result"),
  verdict: document.getElementById("verdict"),
  verdictTitle: document.getElementById("verdictTitle"),
  verdictText: document.getElementById("verdictText"),
  timelineBlock: document.getElementById("timelineBlock"),
  timelineBar: document.getElementById("timelineBar"),
  timelineEnd: document.getElementById("timelineEnd"),
  violations: document.getElementById("violations"),
  lightbox: document.getElementById("lightbox"),
  catalog: document.getElementById("catalog"),
  catalogMeta: document.getElementById("catalogMeta"),
  catalogList: document.getElementById("catalogList"),
};

const state = {
  file: null,        // выбранный файл
  videoUrl: null,    // ссылка на локальное превью
  isBusy: false,     // идёт ли анализ прямо сейчас
};

/* ---------- 3. Вспомогательные функции ---------- */

/** Секунды → «м:сс», например 44.2 → «0:44» */
function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = String(Math.floor(seconds % 60)).padStart(2, "0");
  return `${m}:${s}`;
}

/** Экранирует текст, чтобы его безопасно вставить в HTML */
function escapeHtml(text) {
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
  return String(text ?? "").replace(/[&<>"]/g, (ch) => map[ch]);
}

/** Показывает или скрывает текст ошибки */
function showError(message) {
  el.error.textContent = message;
  el.error.style.display = message ? "block" : "none";
}

/** Обновляет полоску прогресса (0–3) и подпись статуса */
function setStep(step, text) {
  el.progressBars.forEach((bar, i) => bar.classList.toggle("is-active", i < step));
  el.status.textContent = text;
}

/** Пауза в миллисекундах */
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/* ---------- 4. Выбор файла ---------- */

/** Проверяет файл и показывает превью */
function selectFile(file) {
  if (state.isBusy) return;
  showError("");
  if (!file) return;

  if (!/\.(mov|mp4)$/i.test(file.name)) {
    showError("Выберите видео MOV или MP4");
    return;
  }
  if (!file.size) { showError("Файл пустой. Выберите другое видео."); return; }
  if (file.size > CONFIG.maxFileMb * 1024 * 1024) {
    showError(`Файл больше ${CONFIG.maxFileMb} МБ`);
    return;
  }

  resetAll();
  state.file = file;
  el.fileName.textContent = `${file.name} · ${(file.size / 1048576).toFixed(1)} МБ`;

  if (state.videoUrl) URL.revokeObjectURL(state.videoUrl);
  state.videoUrl = URL.createObjectURL(file);
  el.preview.src = state.videoUrl;
  el.preview.style.display = "block";

  el.startBtn.disabled = false;
  setStep(0, "Файл готов к анализу");
}

/* ---------- 5. Работа с API ---------- */

/** Запрос к локальному API с cookie-сессией. Ошибки показываются пользователю. */
async function apiRequest(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      credentials: "same-origin",
      headers: { "X-Forte-Local": "1" },
      signal: typeof AbortSignal !== "undefined" ? AbortSignal.timeout(60000) : undefined,
    });
  } catch (_) {
    throw new Error("Нет ответа от локального сервера. Проверьте, что окно запуска открыто.");
  }

  if (!response.ok) {
    let message = `Ошибка сервера (${response.status})`;
    try {
      const data = await response.json();
      if (data.detail) message = data.detail;
    } catch (_) { /* тело ответа не JSON — оставляем текст по умолчанию */ }
    const errors = {
      401: "Сессия истекла. Повторите запуск анализа.",
      403: "Откройте интерфейс на http://127.0.0.1:8000 на компьютере с сервером.",
      404: "Задание не найдено: возможно, сервер был перезапущен.",
      413: "Видео превышает лимит 200 МиБ.",
      415: "Поддерживаются видео MOV и MP4.",
      429: "Сервер занят. Дождитесь окончания предыдущих проверок.",
    };
    throw new Error(errors[response.status] || message);
  }
  return response.json();
}

/** Отправляет видео на сервер и возвращает job_id */
async function uploadVideo(file) {
  const form = new FormData();
  form.append("file", file);
  const data = await apiRequest("/api/v1/analyze", { method: "POST", body: form });
  return data.job_id;
}

/** Ждёт завершения задачи и возвращает готовый результат */
async function waitForResult(jobId) {
  const startedAt = Date.now();

  while (true) {
    if (Date.now() - startedAt > CONFIG.timeoutMs) {
      throw new Error("Сервис не вернул результат за 5 минут. Попробуйте ещё раз.");
    }
    await sleep(CONFIG.pollIntervalMs);

    const job = await apiRequest(`/api/v1/jobs/${jobId}`);
    if (job.status === "done") {
      const result = job.result ?? job;
      if (!["violation", "no_violation"].includes(result.verdict) || !Array.isArray(result.violations)) {
        throw new Error("Некорректный ответ API. Результат проверки недоступен.");
      }
      return result;
    }
    if (job.status === "failed") {
      const errors = {
        analysis_timeout: "Превышено время анализа. Результат не получен.",
        analysis_failed: "Не удалось обработать видео. Проверьте файл или журнал сервера.",
        invalid_video_or_configuration: "Не удалось прочитать видео или применить настройки. Проверьте файл и профиль камеры; результат не получен.",
        "Local model missing. Run python -m scripts.download_model first.": "Веса модели не установлены. Выполните первоначальную установку проекта.",
        "Unsupported camera aspect. Configure scene zones for this camera.": "Этот формат кадра не подходит профилю камеры. Нужна настройка зон; результат не получен.",
        "No people detected; scene cannot be evaluated": "Люди не обнаружены — оценить эту сцену не удалось.",
      };
      throw new Error(errors[job.error] || job.error || "Не удалось обработать видео");
    }
  }
}

/** Главный сценарий: загрузить → дождаться → показать */
async function startAnalysis() {
  if (!state.file || state.isBusy) return;

  state.isBusy = true;
  el.fileInput.disabled = true;
  showError("");
  el.startBtn.disabled = true;
  el.placeholder.classList.add("is-hidden");
  el.result.classList.add("is-hidden");
  el.loader.style.display = "block";

  try {
    setStep(1, "Подключение к локальному серверу…");
    await apiRequest("/api/v1/session", {method:"POST"});
    setStep(1, "Загрузка видео на этот компьютер…");
    const jobId = await uploadVideo(state.file);

    setStep(2, "Анализ видео…");
    const result = await waitForResult(jobId);

    const seconds = Number(result.meta?.processing_sec);
    setStep(3, Number.isFinite(seconds) ? `Анализ завершён · обработка ${seconds.toFixed(1)} с` : "Анализ завершён");
    renderResult(result);
  } catch (err) {
    setStep(0, "Не удалось выполнить проверку");
    showError(err.message || "Неизвестная ошибка");
    el.placeholder.classList.remove("is-hidden");
    el.startBtn.disabled = false;
  } finally {
    el.loader.style.display = "none";
    state.isBusy = false;
    el.fileInput.disabled = false;
  }
}

/* ---------- 6. Отображение результата ---------- */

/* ---------- 6. Справочник правил (данные из rules.json) ---------- */
const rulesState = { source: "", byId: {} };

/** HTML одной записи справочника */
function catalogItemHtml(rule) {
  return `
    <div class="rule-item">
      <h4>${escapeHtml(rule.title)} <span class="tag">${escapeHtml(rule.point)}</span></h4>
      <p>${escapeHtml(rule.text)}</p>
      <p><b>Что видно на видео:</b> ${escapeHtml(rule.visible)}</p>
      <p><b>Ограничения:</b> ${escapeHtml(rule.limits)}</p>
    </div>`;
}

/** HTML группы справочных пунктов: раскрывающийся список «пункт — суть» */
function referenceGroupHtml(group) {
  const rows = group.items.map(([point, title]) =>
    `<li><b>${escapeHtml(point)}</b> — ${escapeHtml(title)}</li>`).join("");
  return `<details class="ref"><summary>${escapeHtml(group.name)}</summary><ul>${rows}</ul></details>`;
}

/** Запоминает правила и рисует справочник */
function setRules(data) {
  rulesState.source = data.source;
  rulesState.byId = Object.fromEntries(data.rules.map((r) => [r.id, r]));
  el.catalogMeta.textContent = "Источник: " + data.source;
  const groups = (data.reference || []).map(referenceGroupHtml).join("");
  el.catalogList.innerHTML =
    `<h4 class="catalog__h">Включено в прототипе (${data.rules.length})</h4>` +
    data.rules.map(catalogItemHtml).join("") +
    (groups ? `<h4 class="catalog__h">Другие сценарии — пока не проверяются</h4>${groups}` : "");
}

/** Загружает rules.json; если не вышло — просто прячем справочник */
async function loadRules() {
  if (!el.catalog) return; // Вариант без справочника.
  try {
    const response = await fetch("rules.json");
    setRules(await response.json());
  } catch (_) {
    el.catalog.classList.add("is-hidden");
  }
}

/* ---------- 7. Отображение результата ---------- */

/** HTML одного кадра-доказательства */
function frameHtml(frame) {
  return `
    <div class="frame" data-zoom>
      <img src="data:image/jpeg;base64,${escapeHtml(frame.image_base64)}" alt="Кадр ${formatTime(frame.timestamp_sec)}">
      <span>кадр · ${formatTime(frame.timestamp_sec)}</span>
    </div>`;
}

/** Блок «Правило и источник»: берём из справочника по rule_id, иначе из строки rule */
function ruleHtml(violation) {
  const rule = rulesState.byId[violation.rule_id];
  if (rule) {
    return `<div class="rule"><b>Сценарий проверки:</b> ${escapeHtml(rulesState.source)}, <b>${escapeHtml(rule.point)}</b>
              <span class="rule__text">${escapeHtml(rule.text)}</span></div>`;
  }
  if (violation.rule) {
    return `<div class="rule"><b>Правило и источник:</b> ${escapeHtml(violation.rule)}</div>`;
  }
  return "";
}

/** HTML карточки одного нарушения */
function violationHtml(violation, index) {
  const frames = (violation.evidence_frames || []).map(frameHtml).join("")
    || `<div class="frame frame--empty">Кадр недоступен</div>`;

  const rule = ruleHtml(violation);
  const titles = {
    cash_unattended: "Возможное оставление банкнот",
    prev_client_cash: "Банкноты при следующем посетителе",
    safe_left_open: "Возможно открытый сейф",
  };
  const title = titles[violation.type] || rulesState.byId[violation.rule_id]?.title || violation.type || "Событие для проверки";

  return `
    <div class="violation" id="violation-${index}">
      <div class="frames">${frames}</div>
      <div>
        <span class="tag">${formatTime(violation.timecode_sec)} · ${Number(violation.timecode_sec).toFixed(1)} с</span>
        <h3>${escapeHtml(title)}</h3>
        <p>${escapeHtml(violation.description)}</p>
        ${rule}
        <button class="seek-btn" data-seek="${violation.timecode_sec}">▶ Показать момент на видео</button>
      </div>
    </div>`;
}

/** Рисует метки нарушений на таймлайне */
function renderTimeline(violations) {
  const duration = el.preview.duration;
  if (!(duration > 0)) return;

  el.timelineBlock.classList.remove("is-hidden");
  el.timelineEnd.textContent = formatTime(duration);
  el.timelineBar.innerHTML = violations.map((v, i) => {
    const left = Math.min(100, (v.timecode_sec / duration) * 100);
    return `<s class="timeline__mark" style="left:${left}%"
               title="${formatTime(v.timecode_sec)}" data-jump="${i}"></s>`;
  }).join("");
}

/** Показывает вердикт, таймлайн и список нарушений */
function renderResult(result) {
  const violations = result.violations || [];
  const hasViolations = result.verdict === "violation" && violations.length > 0;

  el.placeholder.classList.add("is-hidden");
  el.result.classList.remove("is-hidden");

  el.verdict.classList.toggle("verdict--ok", !hasViolations);
  el.verdictTitle.textContent = hasViolations
    ? "Найдены события для проверки"
    : "По включённому правилу событий нет";
  el.verdictText.textContent = hasViolations
    ? `Найдено событий: ${violations.length}. Это предположения модели, проверьте их вручную.`
    : "Это не подтверждает отсутствие других нарушений.";
  if (result.warnings?.length) {
    el.verdictText.textContent += " Проверка ограничена включёнными сценариями и настройками камеры.";
  }
  state.lastResult = result;

  el.startBtn.classList.add("is-hidden");
  el.resetBtn.classList.remove("is-hidden");

  el.timelineBlock.classList.add("is-hidden");
  if (hasViolations) renderTimeline(violations);

  el.violations.innerHTML = hasViolations ? violations.map(violationHtml).join("") : "";
}

/** Перематывает превью за 1 секунду до события */
function seekVideo(seconds) {
  if (!Number.isFinite(el.preview.duration)) {
    showError("Браузер не может воспроизвести это видео. Откройте исходный файл в проигрывателе на указанной секунде.");
    return;
  }
  el.preview.currentTime = Math.max(0, seconds - 1);
  el.preview.play()?.catch(() => showError("Не удалось включить воспроизведение. Используйте кадры или откройте видео в проигрывателе."));
  el.preview.scrollIntoView({ behavior: "smooth", block: "center" });
}

/** Возвращает форму в исходное состояние */
function resetAll() {
  if (state.isBusy) return;
  state.file = null;
  state.lastResult = null;
  if (state.videoUrl) URL.revokeObjectURL(state.videoUrl);
  state.videoUrl = null;
  el.preview.pause();
  el.fileInput.value = "";
  el.fileName.textContent = "Перетащите MOV/MP4 или нажмите для выбора";
  el.preview.style.display = "none";
  el.preview.removeAttribute("src");
  el.preview.load();
  el.violations.innerHTML = "";
  el.timelineBlock.classList.add("is-hidden");
  el.lightbox.style.display = "none";

  el.result.classList.add("is-hidden");
  el.placeholder.classList.remove("is-hidden");
  el.resetBtn.classList.add("is-hidden");
  el.startBtn.classList.remove("is-hidden");
  el.startBtn.disabled = true;

  showError("");
  setStep(0, "Выберите видеофайл для проверки");
}

/* ---------- 8. Обработчики событий ---------- */

// Выбор файла кнопкой
el.fileInput.addEventListener("change", (e) => selectFile(e.target.files[0]));

// Перетаскивание файла
["dragenter", "dragover"].forEach((name) =>
  el.dropzone.addEventListener(name, (e) => {
    e.preventDefault();
    el.dropzone.classList.add("is-over");
  }));
["dragleave", "drop"].forEach((name) =>
  el.dropzone.addEventListener(name, (e) => {
    e.preventDefault();
    el.dropzone.classList.remove("is-over");
  }));
el.dropzone.addEventListener("drop", (e) => selectFile(e.dataTransfer.files[0]));

// Кнопки
el.startBtn.addEventListener("click", startAnalysis);
el.resetBtn.addEventListener("click", resetAll);

// Клики внутри результата: метки таймлайна, «показать момент», увеличение кадра
document.addEventListener("click", (e) => {
  const mark = e.target.closest("[data-jump]");
  if (mark) {
    document.getElementById(`violation-${mark.dataset.jump}`)
      .scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }

  const seekBtn = e.target.closest("[data-seek]");
  if (seekBtn) {
    seekVideo(Number(seekBtn.dataset.seek));
    return;
  }

  const frame = e.target.closest("[data-zoom]");
  if (frame) {
    el.lightbox.querySelector("img").src = frame.querySelector("img").src;
    el.lightbox.style.display = "grid";
    return;
  }

  if (e.target.closest("#lightbox")) el.lightbox.style.display = "none";
});

// Старт
loadRules();
el.preview.addEventListener("loadedmetadata", () => {
  if (state.lastResult?.violations?.length) renderTimeline(state.lastResult.violations);
});

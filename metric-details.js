/* Public aggregate details only; no personal records are requested. */
"use strict";
(function () {
  const labels = {
    training: ["Обучены в активной базе", "Курьеры активной базы 1С", "Обучение не подтверждено"],
    slot_fill: ["Занятые места", "Всего мест", "Свободные места"],
    shift_marked: ["Курьеры с записью на день", "Курьеры в расчётной базе", "Без записи в этой базе"],
    planned_attendance: ["Вышли по плану", "Курьеры в плане", "Остальные в плане"],
    planned_late: ["Опоздали от 15 минут", "Вышли по плану", "Без опоздания от 15 минут"],
    unplanned_work: ["Вышли вне плана", "Всего фактически вышли", "Вышли по плану"],
    planned_completion: ["Завершили учитываемые смены", "Курьеры в расчёте", "Остальные в расчёте"],
    medical: ["С действующей ЛМК", "Курьеры в отчёте ЛМК", "Без действующей ЛМК"]
  };
  const style = document.createElement("style");
  style.textContent = `.metric-detail-trigger{appearance:none;border:0;background:transparent;padding:0;cursor:pointer;font:inherit;border-radius:12px}.metric-detail-trigger:hover .cell{box-shadow:0 0 0 2px #64748b}.metric-detail-trigger:focus-visible{outline:3px solid #2563eb;outline-offset:3px}.metric-dialog{border:0;border-radius:20px;padding:26px;width:min(620px,calc(100vw - 32px));max-height:85vh;overflow:auto;box-sizing:border-box;color:#18364b;box-shadow:0 24px 80px #10223455;font:15px/1.5 system-ui}.metric-dialog::backdrop{background:#10223488}.metric-dialog h2{font-size:22px;line-height:1.3;margin:10px 0}.metric-dialog .detail-close{float:right;border:1px solid #cbd5e1;background:white;border-radius:8px;padding:7px 12px;cursor:pointer;font:inherit}.metric-dialog .detail-context{color:#64748b;margin:0}.metric-dialog .detail-value{font-size:34px;font-weight:750;margin:16px 0 6px}.metric-dialog dl{display:grid;grid-template-columns:1fr auto;gap:10px;margin:18px 0;padding:16px;background:#f1f5f9;border-radius:12px}.metric-dialog dt,.metric-dialog dd{margin:0}.metric-dialog dd{font-weight:700}.metric-dialog .detail-note{color:#475569}.metric-dialog .detail-formula{font-weight:650}.metric-dialog .detail-method{border-top:1px solid #e2e8f0;padding-top:14px}@media print{.metric-dialog{position:static;box-shadow:none}.metric-dialog .detail-close{display:none}}`;
  document.head.append(style);
  const dialog = document.createElement("dialog");
  dialog.className = "metric-dialog";
  dialog.setAttribute("aria-labelledby", "metric-detail-title");
  document.body.append(dialog);
  let opener;
  function element(tag, text, className) {
    const node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function open(detail, trigger) {
    opener = trigger;
    dialog.replaceChildren();
    const close = element("button", "Закрыть", "detail-close");
    close.type = "button";
    close.addEventListener("click", () => dialog.close());
    const title = element("h2", detail.name);
    title.id = "metric-detail-title";
    dialog.append(close, element("p", "ДС " + detail.shop + " · " + detail.day.split("-").reverse().join("."), "detail-context"), title);
    const metric = detail.metric;
    dialog.append(element("p", metric.value === null ? "Нет расчёта" : metric.value.toLocaleString("ru-RU", {maximumFractionDigits: 2}) + "%", "detail-value"));
    if (metric.value !== null) {
      dialog.append(element("p", metric.numerator + " ÷ " + metric.denominator + " × 100 = " + metric.value.toLocaleString("ru-RU") + "%", "detail-formula"));
    }
    let terms = labels[detail.key];
    if (metric.basis === "current_limited_bookings_unique_couriers") {
      if (detail.key === "planned_attendance") terms = ["Вышли из записавшихся", "Записались в лимитированные слоты", "Остальные записавшиеся"];
      if (detail.key === "planned_late") terms = ["Опоздали от 15 минут", "Вышли в лимитированные слоты", "Без опоздания от 15 минут"];
    }
    const list = document.createElement("dl");
    [metric.numerator, metric.denominator].forEach((value, index) => list.append(element("dt", terms[index]), element("dd", value === null ? "Нет данных" : String(value))));
    if (Number.isSafeInteger(metric.numerator) && Number.isSafeInteger(metric.denominator) && metric.denominator >= metric.numerator) {
      list.append(element("dt", terms[2]), element("dd", String(metric.denominator - metric.numerator)));
    }
    dialog.append(list, element("p", detail.explanation, "detail-method"));
    if (detail.key === "medical") dialog.append(element("p", "Группа без действующей ЛМК включает отсутствие и просрочку. Раздельные количества в этой выгрузке не переданы.", "detail-note"));
    if (detail.key === "slot_fill" && metric.numerator > metric.denominator) dialog.append(element("p", "Записей сверх вместимости: " + (metric.numerator - metric.denominator), "detail-note"));
    dialog.append(element("p", "Источник: " + detail.source, "detail-note"));
    dialog.append(element("p", "Данные получены: " + new Date(detail.reportedAt).toLocaleString("ru-RU", {timeZone: "Europe/Moscow"}) + " МСК", "detail-note"));
    dialog.showModal();
    close.focus();
    window.dispatchEvent(new CustomEvent('metric-detail-open',{detail:{...detail,dialog}}));
  }
  dialog.addEventListener("click", event => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
  dialog.addEventListener("keydown", event => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); dialog.close(); }
  }, true);
  dialog.addEventListener("close", () => {
    if (opener && opener.isConnected) opener.focus();
    else document.getElementById("refreshData")?.focus();
  });
  window.metricDetails = {
    attach(cell, detail) {
      if (!labels[detail.key] || cell.dataset.source === "manual") return;
      const button = element("button", "", "metric-detail-trigger");
      button.type = "button";
      button.setAttribute("aria-label", "Подробнее: " + detail.name + ", " + detail.day.split("-").reverse().join("."));
      button.setAttribute("aria-haspopup", "dialog");
      button.title = "Открыть расчёт показателя";
      while (cell.firstChild) button.append(cell.firstChild);
      cell.append(button);
      button.addEventListener("click", () => open(detail, button));
    }
  };
}());

/* This file reads public aggregates only. Authentication stays on the exporter. */
"use strict";
(function () {
  const shop = Number(document.getElementById("storeSelect").value);
  const initialDates = dates.map(d => "2026-" + d.slice(3, 5) + "-" + d.slice(0, 2));
  const historical = metrics.map(m => m.values.slice());
  const status = document.getElementById("dataStatus");
  const refresh = document.getElementById("refreshData");
  let busy = false;
  let lastSuccess = "";

  function validate(payload) {
    if (!payload || payload.schema_version !== 1 || !Array.isArray(payload.records)) throw Error("format");
    const seen = new Set();
    return payload.records.map(row => {
      if (!row || ![5818, 7745].includes(row.shop_id) ||
          !/^\d{4}-\d{2}-\d{2}$/.test(row.date) ||
          !Number.isFinite(Date.parse(row.date)) || new Date(row.date).toISOString().slice(0, 10) !== row.date ||
          ![row.capacity, row.booked_places].every(n => Number.isSafeInteger(n) && n >= 0) ||
          !Number.isFinite(Date.parse(row.reported_at)) || row.source !== "slots_export") throw Error("format");
      const key = row.shop_id + ":" + row.date;
      if (seen.has(key)) throw Error("duplicate");
      seen.add(key);
      const expected = row.capacity ? row.booked_places / row.capacity * 100 : null;
      if ((!row.capacity && (row.booked_places || row.fill_percent !== null)) ||
          (row.capacity && (typeof row.fill_percent !== "number" || !Number.isFinite(row.fill_percent) || Math.abs(expected - row.fill_percent) > .011))) throw Error("counts");
      return row;
    });
  }

  function update(rows) {
    const own = rows.filter(r => r.shop_id === shop);
    if (!own.length) {
      status.textContent = lastSuccess ? lastSuccess + " · Новый файл не содержит данных этой ДС; сохранён предыдущий отчёт." : "Для этой ДС новых выгрузок пока нет. Показана история.";
      return;
    }
    const days = Array.from(new Set(initialDates.concat(own.map(r => r.date)))).sort();
    // The existing dashboard has one column per day/month; do not merge different years.
    if (days.some(d => !d.startsWith("2026-"))) throw Error("year");
    const indexes = new Map(days.map((day, i) => [day, i]));
    const next = metrics.map((metric, mi) => days.map(day => {
      const oldIndex = initialDates.indexOf(day);
      return oldIndex < 0 ? null : historical[mi][oldIndex];
    }));
    const imported = new Map();
    own.forEach(row => {
      next[2][indexes.get(row.date)] = row.fill_percent === null ? null : String(row.fill_percent);
      imported.set(indexes.get(row.date), row);
    });
    dates.splice(0, dates.length, ...days.map(d => d.slice(8) + "." + d.slice(5, 7)));
    metrics.forEach((metric, i) => { metric.values = next[i]; });
    render();
    document.querySelector("col.day-col").span = days.length;
    document.querySelector(".panel-note").textContent = metrics.length + " метрик · Дней: " + days.length + " · Цель";
    document.querySelector(".description").textContent = "Ежедневные показатели · " + dates[0] + "–" + dates[dates.length - 1] + ".2026";
    const cells = document.querySelectorAll("#metricsBody tr")[2].querySelectorAll("td");
    imported.forEach((row, i) => {
      cells[i].title = row.capacity ? "Лимитированные слоты: занято " + row.booked_places + " из " + row.capacity + " мест. Один курьер может занимать несколько слотов." : "Нет данных о потребности: вместимость лимитированных слотов равна нулю.";
      cells[i].dataset.source = "slots_export";
    });
    const latest = own.slice().sort((a, b) => a.date.localeCompare(b.date)).pop();
    const time = new Intl.DateTimeFormat("ru-RU", {timeZone: "Europe/Moscow", dateStyle: "short", timeStyle: "short"}).format(new Date(latest.reported_at));
    lastSuccess = "Выгрузка за " + latest.date.slice(8) + "." + latest.date.slice(5, 7) + "." + latest.date.slice(0, 4) + " · Сформирована " + time + " МСК. Автоматически загружено только заполнение слотов; остальные новые значения — прочерки.";
    status.textContent = lastSuccess;
    if (!status.dataset.positioned) {
      const viewport = document.querySelector(".table-scroll");
      viewport.scrollLeft = viewport.scrollWidth;
      status.dataset.positioned = "true";
    }
  }

  async function load() {
    if (busy) return;
    busy = true;
    refresh.disabled = true;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch("data/dashboard.json", {cache: "no-store", signal: controller.signal});
      if (!response.ok) throw Error("http");
      update(validate(await response.json()));
    } catch (_) {
      status.textContent = lastSuccess ? lastSuccess + " · Новую выгрузку загрузить не удалось; сохранены последние данные." : "Новую выгрузку загрузить не удалось. Показаны исторические данные.";
    } finally {
      clearTimeout(timer);
      busy = false;
      refresh.disabled = false;
    }
  }
  refresh.addEventListener("click", load);
  load();
  setInterval(() => { if (!document.hidden) load(); }, 60000);
}());

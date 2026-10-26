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
  const metricIndexes = {slot_fill: 2, shift_marked: 1, planned_attendance: 3,
    planned_late: 4, unplanned_work: 5, planned_completion: 6};
  const reasons = {
    zero_denominator: "Нет данных для знаменателя; это не 0%.",
    assigned_roster_not_verified: "Полный список закреплённых курьеров ещё не подтверждён.",
    active_base_incomplete: "Не удалось полностью получить расписание самого ДС за выбранный день и четыре предыдущих дня.",
    completion_history_incomplete: "Не удалось полностью проверить ночные смены предыдущих дней по правилу даты фактического завершения.",
    bookings_outside_verified_roster: "Есть записавшиеся вне подтверждённого списка курьеров; нужна сверка.",
    frozen_plan_missing: "Нет сохранённого плана на 23:59 накануне. Текущие записи не подменяют план.",
    planned_booking_missing_from_current_data: "Запись из сохранённого плана исчезла из текущих данных; нужна история изменений.",
    planned_slot_times_changed: "Время слота изменилось после фиксации плана; нужна сверка.",
    unknown_planned_shift_status: "У плановой записи неизвестный статус смены.",
    unknown_shift_status: "Не все фактические статусы смен распознаны.",
    shift_end_or_final_status_missing: "Не у всех плановых курьеров есть время окончания или окончательный статус смены."
  };

  function validate(payload) {
    if (!payload || payload.schema_version !== 1 || !Array.isArray(payload.records)) throw Error("format");
    const seen = new Set();
    return payload.records.map(row => {
      if (!row || ![5818, 7745, 4747, 8092].includes(row.shop_id) ||
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
      if (row.metrics !== undefined) {
        if (!row.metrics || typeof row.metrics !== "object" || Array.isArray(row.metrics)) throw Error("metrics");
        Object.entries(row.metrics).forEach(([key, metric]) => {
          if (!Object.prototype.hasOwnProperty.call(metricIndexes, key) || !metric ||
              (metric.reason !== null && !Object.prototype.hasOwnProperty.call(reasons, metric.reason))) throw Error("metric");
          for (const count of [metric.numerator, metric.denominator]) {
            if (count !== null && (!Number.isSafeInteger(count) || count < 0)) throw Error("metric counts");
          }
          if (metric.value === null) {
            if (!metric.reason) throw Error("missing reason");
          } else if (metric.reason !== null || typeof metric.value !== "number" ||
                     !Number.isFinite(metric.value) || !metric.denominator ||
                     metric.numerator === null ||
                     Math.abs(metric.value - metric.numerator / metric.denominator * 100) > .011) throw Error("metric percentage");
        });
        if (row.metrics.slot_fill && (row.metrics.slot_fill.value !== row.fill_percent ||
            row.metrics.slot_fill.numerator !== row.booked_places || row.metrics.slot_fill.denominator !== row.capacity)) throw Error("fill mismatch");
      }
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
      if (!row.metrics || row.metrics.slot_fill) {
        next[2][indexes.get(row.date)] = row.fill_percent === null ? null : String(row.fill_percent);
      }
      Object.entries(row.metrics || {}).forEach(([key, metric]) => {
        next[metricIndexes[key]][indexes.get(row.date)] = metric.value === null ? null : String(metric.value);
      });
      imported.set(indexes.get(row.date), row);
    });
    dates.splice(0, dates.length, ...days.map(d => d.slice(8) + "." + d.slice(5, 7)));
    metrics.forEach((metric, i) => { metric.values = next[i]; });
    render();
    document.querySelector("col.day-col").span = days.length;
    document.querySelector(".panel-note").textContent = metrics.length + " метрик · Дней: " + days.length + " · Цель";
    document.querySelector(".description").textContent = "Ежедневные показатели · " + dates[0] + "–" + dates[dates.length - 1] + ".2026";
    const rowsInTable = document.querySelectorAll("#metricsBody tr");
    const cells = rowsInTable[2].querySelectorAll("td");
    imported.forEach((row, i) => {
      if (!row.metrics || row.metrics.slot_fill) {
        cells[i].title = row.capacity ? "Лимитированные слоты: занято " + row.booked_places + " из " + row.capacity + " мест. Один курьер может занимать несколько слотов." : "Нет данных о потребности: вместимость лимитированных слотов равна нулю.";
        cells[i].dataset.source = "slots_export";
      }
      Object.entries(row.metrics || {}).forEach(([key, metric]) => {
        const cell = rowsInTable[metricIndexes[key]].querySelectorAll("td")[i];
        const basis = {
          slot_fill: " мест. Один курьер может занимать несколько слотов.",
          shift_marked: metric.basis === "direct_shop_scheduled_unique_5d_including_day" ?
            " уникальных курьеров активной базы, записавшихся на выбранный день в ДС или его кластеры. База — расписание самого ДС за этот день и четыре предыдущих. Наличие записи не подтверждает фактический выход." :
            " уникальных курьеров из закреплённых за ДС.",
          planned_attendance: " курьеров из зафиксированного накануне плана.",
          planned_late: " курьеров, опоздавших среди вышедших по плану.",
          unplanned_work: " вышедших курьеров: ручной выход без записи в зафиксированном плане.",
          planned_completion: " курьеров, завершивших все плановые смены. Допуск окончания — 10 минут, как на исходном сайте."
        };
        if (metric.basis === "current_limited_bookings_unique_couriers") {
          basis.planned_attendance = " уникальных записавшихся в лимитированные слоты, имеющих статус «вышел», «раньше» или «опоздал». Текущий список записей; план накануне не подтверждён. «Ожидается» пока не считается выходом, день может быть не завершён.";
          basis.planned_late = " вышедших уникальных курьеров лимитированных слотов с хотя бы одним опозданием. По текущим карточкам слотов; план накануне не подтверждён.";
        }
        if (metric.basis === "current_limited_all_shifts_site_10min_tolerance") {
          basis.planned_completion = " уникальных записавшихся курьеров, завершивших все свои лимитированные слоты. Сравнивается фактический уход с окончанием слота, допуск — 10 минут. По текущим карточкам; план накануне не подтверждён. Неявка считается незавершением.";
        }
        if (metric.basis === "slot_completion_by_actual_night_end_date") {
          basis.planned_completion = " уникальных курьеров, завершивших все учитываемые лимитированные слоты. Ночная смена относится к дате фактического ухода по Москве; открытая ночная смена пока не включается. Дневная — к дате слота. Допуск окончания — 10 минут. Даты других метрик не меняются.";
        }
        cell.title = metric.value === null ? reasons[metric.reason] :
          "По данным сайта: " + metric.numerator + " из " + metric.denominator + basis[key];
        cell.dataset.source = "slots_export";
      });
    });
    const latest = own.slice().sort((a, b) => a.date.localeCompare(b.date)).pop();
    const time = new Intl.DateTimeFormat("ru-RU", {timeZone: "Europe/Moscow", dateStyle: "short", timeStyle: "short"}).format(new Date(latest.reported_at));
    const ready = latest.metrics ? Object.values(latest.metrics).filter(metric => metric.value !== null).length : (latest.fill_percent === null ? 0 : 1);
    lastSuccess = "Выгрузка за " + latest.date.slice(8) + "." + latest.date.slice(5, 7) + "." + latest.date.slice(0, 4) + " · Сформирована " + time + " МСК. Рассчитано автоматических показателей: " + ready + " из 6. Причины прочерков — в подсказках ячеек.";
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

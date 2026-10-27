/* DS 5818 only. Uses the same merged manual/API values as the table. */
"use strict";
(function () {
  const root = document.getElementById("trendOverview");
  if (!root) return;
  const select = document.getElementById("trendMetric");
  const period = document.getElementById("trendPeriod");
  const svg = document.getElementById("trendChart");
  const summary = document.getElementById("trendSummary");
  const hover = document.getElementById("trendHover");
  const transition = "2026-10-23";
  const changedSource = new Set([1, 2, 3, 4, 5, 6]);
  const ns = "http://www.w3.org/2000/svg";
  let selected = 2;
  const number = value => {
    if (value === null || value === undefined || value === "") return null;
    const n = Number(String(value).replace(",", "."));
    return Number.isFinite(n) ? n : null;
  };
  const fmt = n => n === null ? "—" : n.toLocaleString("ru-RU", {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const iso = day => "2026-" + day.slice(3, 5) + "-" + day.slice(0, 2);
  function element(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function shape(tag, attrs, text) {
    const el = document.createElementNS(ns, tag);
    Object.entries(attrs || {}).forEach(([key, value]) => el.setAttribute(key, value));
    if (text !== undefined) el.textContent = text;
    svg.appendChild(el);
    return el;
  }
  function daysInPeriod() {
    const all = dates.map((day, index) => ({day, index, date: iso(day)}));
    if (period.value === "after") return all.filter(d => d.date >= transition);
    if (period.value === "week" && all.length) {
      const start = Date.parse(all[all.length - 1].date) - 6 * 86400000;
      return all.filter(d => Date.parse(d.date) >= start);
    }
    return all;
  }
  function analyze(index, days) {
    const points = days.map(d => ({...d, value: number(metrics[index].values[d.index])}));
    const valid = points.filter(p => p.value !== null);
    const first = valid[0], last = valid[valid.length - 1];
    const mixed = changedSource.has(index) && valid.some(p => p.date < transition) && valid.some(p => p.date >= transition);
    const delta = valid.length >= 2 && !mixed ? Math.round((last.value - first.value) * 100) / 100 : null;
    const improvement = delta === null ? null : (metrics[index].better === "low" ? -delta : delta);
    const tone = improvement === null || improvement === 0 ? "" : improvement > 0 ? "good" : "bad";
    const label = mixed ? "Разные источники" : delta === null ? "Мало данных" : delta === 0 ? "Без изменений" :
      (delta > 0 ? "+" : "−") + fmt(Math.abs(delta)) + " п.п.";
    return {points, valid, first, last, mixed, delta, tone, label};
  }
  function overview(days) {
    root.replaceChildren();
    metrics.forEach((metric, index) => {
      const stats = analyze(index, days);
      const button = element("button", "trends-card");
      button.type = "button";
      button.dataset.metric = index;
      button.setAttribute("aria-pressed", String(index === selected));
      button.appendChild(element("span", "trends-card-name", (index + 1) + ". " + metric.name));
      button.appendChild(element("span", "trends-card-value", stats.last ? fmt(stats.last.value) + "%" : "—"));
      const meta = element("span", "trends-card-meta");
      meta.appendChild(element("span", "", stats.last ? stats.last.day : "Нет значений"));
      meta.appendChild(element("span", "trends-badge " + stats.tone, stats.label));
      button.appendChild(meta);
      button.title = metric.name + ". " + (metric.better === "low" ? "Снижение — улучшение." : "Рост — улучшение.");
      button.addEventListener("click", () => {selected = index; select.value = String(index); render();});
      root.appendChild(button);
    });
  }
  function summaryCard(label, value, detail, tone) {
    const box = element("div", "trends-stat " + (tone || ""));
    box.appendChild(element("span", "trends-stat-label", label));
    box.appendChild(element("strong", "trends-stat-value", value));
    box.appendChild(element("small", "", detail));
    summary.appendChild(box);
  }
  function plot(stats, days) {
    svg.replaceChildren();
    document.getElementById("trendEmpty").hidden = stats.valid.length !== 0;
    svg.style.display = stats.valid.length ? "block" : "none";
    if (!stats.valid.length) return;
    const width = Math.max(300, svg.parentElement.clientWidth), height = 300;
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("aria-label", metrics[selected].name + ", " + stats.first.day + "–" + stats.last.day);
    const left = 46, right = width - 18, top = 24, bottom = height - 36;
    const maximum = Math.ceil(Math.max(100, number(metrics[selected].goal) || 0, ...stats.valid.map(p => p.value)) / 20) * 20;
    const start = Date.parse(days[0].date), end = Date.parse(days[days.length - 1].date);
    const x = day => start === end ? (left + right) / 2 : left + (Date.parse(day) - start) / (end - start) * (right - left);
    const y = value => bottom - value / maximum * (bottom - top);
    for (let i = 0; i <= 5; i++) {
      const value = maximum * i / 5;
      shape("line", {x1: left, x2: right, y1: y(value), y2: y(value), stroke: "#e9eef5"});
      shape("text", {x: left - 9, y: y(value) + 4, "text-anchor": "end", fill: "#78869a", "font-size": 11}, String(Math.round(value)));
    }
    const labelsEvery = Math.max(1, Math.ceil(days.length / (width < 600 ? 5 : 10)));
    days.forEach((day, index) => {
      if (index % labelsEvery !== 0 && index !== days.length - 1) return;
      shape("text", {x: x(day.date), y: height - 11, "text-anchor": "middle", fill: "#78869a", "font-size": 11}, day.day);
    });
    const goal = number(metrics[selected].goal);
    if (goal !== null) shape("line", {x1: left, x2: right, y1: y(goal), y2: y(goal), stroke: "#26986a", "stroke-width": 1.5, "stroke-dasharray": "6 5"});
    if (days.some(d => d.date < transition) && days.some(d => d.date >= transition)) {
      const boundary = x("2026-10-23") - (right - left) / Math.max(1, (end - start) / 86400000) / 2;
      shape("line", {x1: boundary, x2: boundary, y1: top, y2: bottom, stroke: "#8b5cf6", "stroke-width": 2, "stroke-dasharray": "5 4"});
      shape("text", {x: Math.min(right - 50, boundary + 7), y: top - 8, fill: "#7c3aed", "font-size": 10}, "23 октября");
    }
    let path = "", previous = null;
    stats.points.forEach(point => {
      if (point.value === null) {previous = null; return;}
      const crossing = previous && previous.date < transition && point.date >= transition && changedSource.has(selected);
      path += (!previous || crossing ? "M" : "L") + x(point.date) + "," + y(point.value) + " ";
      previous = point;
    });
    shape("path", {d: path, fill: "none", stroke: "#285dcc", "stroke-width": 2.5, "stroke-linejoin": "round", "stroke-linecap": "round"});
    stats.valid.forEach(point => {
      shape("circle", {cx: x(point.date), cy: y(point.value), r: 4, fill: "#285dcc", stroke: "white", "stroke-width": 1.5});
      const label = point.day + ": " + fmt(point.value) + "%";
      const hit = shape("circle", {cx: x(point.date), cy: y(point.value), r: 10, fill: "transparent", class: "trend-hit", tabindex: 0, role: "img", "aria-label": label});
      const title = document.createElementNS(ns, "title"); title.textContent = label; hit.appendChild(title);
      ["pointerenter", "focus", "click"].forEach(event => hit.addEventListener(event, () => {hover.textContent = metrics[selected].name + " · " + label;}));
    });
  }
  function render() {
    const days = daysInPeriod(), stats = analyze(selected, days);
    overview(days);
    summary.replaceChildren();
    summaryCard("Начало периода", stats.first ? fmt(stats.first.value) + "%" : "—", stats.first ? stats.first.day : "Нет данных");
    summaryCard("Последнее значение", stats.last ? fmt(stats.last.value) + "%" : "—", stats.last ? stats.last.day : "Нет данных");
    const outcome = stats.mixed ? "Сравнение некорректно" : stats.delta === null ? "Нужны две даты" : stats.delta === 0 ? "Без изменений" : stats.tone === "good" ? "Улучшение" : "Ухудшение";
    summaryCard("Изменение", stats.label, outcome, stats.tone);
    document.getElementById("trendDirection").textContent = metrics[selected].better === "low" ? "Меньше — лучше" : "Больше — лучше";
    document.getElementById("trendComparisonNote").textContent = stats.mixed ?
      "Период пересекает смену инструмента 23 октября: значения показаны, но их разность не оценивается как улучшение или ухудшение. Выбери период с 23 октября." :
      (stats.valid.length ? "Данные за " + stats.valid.length + " из " + days.length + " дней выбранного периода." : "");
    hover.textContent = "Наведи на точку или выбери её клавишей Tab, чтобы увидеть значение.";
    plot(stats, days);
  }
  metrics.forEach((metric, index) => {
    const option = element("option", "", (index + 1) + ". " + metric.name);
    option.value = index; select.appendChild(option);
  });
  select.value = String(selected);
  select.addEventListener("change", () => {selected = Number(select.value); render();});
  period.addEventListener("change", render);
  window.addEventListener("courier-metrics-rendered", render);
  let resize;
  window.addEventListener("resize", () => {cancelAnimationFrame(resize); resize = requestAnimationFrame(() => {const days = daysInPeriod(); plot(analyze(selected, days), days);});});
  render();
}());

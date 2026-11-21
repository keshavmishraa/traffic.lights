"use strict";

const get = id => document.getElementById(id);
const canvas = get("map");
const ctx = canvas.getContext("2d");
const width = 840;
const height = 464;
const scale = canvas.width / width;
const motion = matchMedia("(prefers-reduced-motion: reduce)");
const muted = "#a8b7bc";
const amber = "#ffd18b";

const roads = {
  A: {
    name: "West", color: "#8ce6c2", label: [28, 94], signal: [305, 310],
    start: [304, 252], end: [304, 175], edge: [37, 175], direction: [1, 0],
    queueGap: 44, capacity: 6, badge: [0, -19],
  },
  B: {
    name: "East", color: "#94cbff", label: [674, 94], signal: [535, 118],
    start: [536, 175], end: [536, 252], edge: [803, 252], direction: [-1, 0],
    queueGap: 44, capacity: 6, badge: [0, -19],
  },
  C: {
    name: "South", color: "#d2b8ff", label: [551, 389], signal: [515, 327],
    start: [455, 331], end: [383, 331], edge: [383, 434], direction: [0, -1],
    queueGap: 47, capacity: 3, badge: [19, 0],
  },
};

function roundRect(context, x, y, w, h, radius, fill) {
  context.beginPath();
  context.roundRect(x, y, w, h, radius);
  context.fillStyle = fill;
  context.fill();
}

function line(context, points) {
  context.beginPath();
  context.moveTo(...points[0]);
  for (const point of points.slice(1)) context.lineTo(...point);
  context.stroke();
}

function text(context, value, x, y, color, font, align = "left") {
  context.fillStyle = color;
  context.font = font;
  context.textAlign = align;
  context.textBaseline = "middle";
  context.fillText(value, x, y);
}

function buildBaseMap() {
  const base = document.createElement("canvas");
  base.width = canvas.width;
  base.height = canvas.height;
  const map = base.getContext("2d");
  map.scale(scale, scale);

  const ground = map.createLinearGradient(0, 0, width, height);
  ground.addColorStop(0, "#192b2c");
  ground.addColorStop(1, "#111e23");
  map.fillStyle = ground;
  map.fillRect(0, 0, width, height);

  map.strokeStyle = "#304248";
  map.lineWidth = 0.5;
  for (let x = 12; x < width; x += 24) line(map, [[x, 0], [x, height]]);
  for (let y = 12; y < height; y += 24) line(map, [[0, y], [width, y]]);

  map.fillStyle = "#2b353e";
  map.fillRect(0, 137, width, 154);
  map.fillRect(347, 290, 146, height - 290);

  map.lineWidth = 2;
  map.strokeStyle = "#62717a";
  line(map, [[0, 137], [width, 137]]);
  line(map, [[0, 291], [335, 291], [347, 303], [347, height]]);
  line(map, [[width, 291], [505, 291], [493, 303], [493, height]]);
  map.fillStyle = "#2b353e";
  map.beginPath();
  map.moveTo(335, 290);
  map.lineTo(505, 290);
  map.lineTo(492, 303);
  map.lineTo(348, 303);
  map.fill();

  map.strokeStyle = "#87929a";
  map.lineWidth = 1.5;
  map.setLineDash([12, 10]);
  line(map, [[0, 214], [328, 214]]);
  line(map, [[512, 214], [width, 214]]);
  line(map, [[419, 312], [419, height]]);
  map.setLineDash([]);

  map.strokeStyle = "#b8c3c7";
  map.lineWidth = 3;
  line(map, [[328, 225], [328, 281]]);
  line(map, [[512, 148], [512, 203]]);
  line(map, [[430, 307], [484, 307]]);

  map.strokeStyle = "#78868e";
  map.lineWidth = 2;
  for (const [lane, road] of Object.entries(roads)) {
    const [x, y] = road.edge;
    const [dx, dy] = road.direction;
    line(map, [[x - dx * 7 - dy * 6, y - dy * 7 + dx * 6], [x - dx * 13, y - dy * 13],
               [x - dx * 7 + dy * 6, y - dy * 7 - dx * 6]]);
    const [labelX, labelY] = road.label;
    roundRect(map, labelX, labelY - 14, 29, 29, 7, "#22353a");
    text(map, lane, labelX + 14.5, labelY + 1, road.color, "700 17px system-ui", "center");
    text(map, road.name + " approach", labelX + 39, labelY + 1, "#c8d4d5", "600 16px system-ui");
  }
  return base;
}

const baseMap = buildBaseMap();
ctx.scale(scale, scale);

function buildRoute(from, to) {
  const entry = roads[from];
  const exit = roads[to];
  const start = entry.start;
  const end = exit.end;
  const reach = (Math.abs(end[0] - start[0]) + Math.abs(end[1] - start[1])) * 0.46;
  const controlIn = start.map((coordinate, axis) => coordinate + reach * entry.direction[axis]);
  const controlOut = end.map((coordinate, axis) => coordinate + reach * exit.direction[axis]);

  const points = [start];
  for (let step = 1; step <= 28; step++) {
    const t = step / 28;
    const u = 1 - t;
    points.push(start.map((coordinate, axis) =>
      u ** 3 * coordinate + 3 * u ** 2 * t * controlIn[axis] +
      3 * u * t ** 2 * controlOut[axis] + t ** 3 * end[axis]));
  }
  points.push(exit.edge);

  const distances = [0];
  for (let index = 1; index < points.length; index++) {
    const [x, y] = points[index];
    const [previousX, previousY] = points[index - 1];
    distances.push(distances[index - 1] + Math.hypot(x - previousX, y - previousY));
  }
  return {points, distances};
}

function positionOnRoute({points, distances}, progress) {
  const distance = progress * distances.at(-1);
  const index = distances.findIndex((length, i) => i > 0 && length >= distance);
  const ratio = (distance - distances[index - 1]) / (distances[index] - distances[index - 1]);
  const [x, y] = points[index - 1];
  const [endX, endY] = points[index];
  return [x + (endX - x) * ratio, y + (endY - y) * ratio, Math.atan2(endY - y, endX - x)];
}

function drawSignal(road, color) {
  const [x, y] = road.signal;
  roundRect(ctx, x - 22, y - 10, 44, 20, 7, "#0e171c");
  for (const [offset, signal, lit, dim] of [
    [-11, "RED", "#fda3a4", "#54383e"], [11, "GREEN", "#8ce6b8", "#2a4842"],
  ]) {
    if (color === signal) {
      ctx.shadowColor = lit;
      ctx.shadowBlur = 9;
    }
    roundRect(ctx, x + offset - 4.5, y - 4.5, 9, 9, 4.5, color === signal ? lit : dim);
    ctx.shadowBlur = 0;
  }
}

function drawCar(x, y, angle, color) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(angle);
  roundRect(ctx, -17, -10, 37, 22, 7, "#0c131bb0");
  roundRect(ctx, -18, -10, 36, 20, 6, color);
  roundRect(ctx, -9, -7, 19, 14, 3, "#263941");
  roundRect(ctx, -5, -6, 10, 12, 2, color);
  roundRect(ctx, 14, -7, 3, 4, 1.5, "#fff3d5");
  roundRect(ctx, 14, 3, 3, 4, 1.5, "#fff3d5");
  roundRect(ctx, -17, -7, 2, 4, 1, "#c16d73");
  roundRect(ctx, -17, 3, 2, 4, 1, "#c16d73");
  ctx.restore();
}

function drawMap(state, route, progress) {
  ctx.drawImage(baseMap, 0, 0, width, height);
  if (route) {
    ctx.save();
    ctx.strokeStyle = "#896e4d";
    ctx.lineWidth = 8;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    line(ctx, route.points);
    ctx.strokeStyle = amber;
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 9]);
    line(ctx, route.points);
    ctx.restore();

    const [x, y] = route.points.at(-1);
    roundRect(ctx, x - 11, y - 11, 22, 22, 11, "#ffe3ad");
    text(ctx, state.current_destination_lane, x, y + 0.5, "#282219", "750 13px system-ui", "center");
  }

  for (const [lane, road] of Object.entries(roads)) {
    const light = state?.lanes.find(item => item.lane === lane);
    drawSignal(road, light?.color);
    const [dx, dy] = road.direction;
    const angle = Math.atan2(dy, dx);
    const [startX, startY] = road.start;
    const shift = route && lane === state.current_lane
      ? Math.max(0, road.queueGap - progress * route.distances.at(-1)) : 0;
    for (const [index, car] of (light?.cars ?? []).slice(0, road.capacity).entries()) {
      const distance = shift + index * road.queueGap;
      const x = startX - distance * dx;
      const y = startY - distance * dy;
      drawCar(x, y, angle, "#9eb4c1");
      const [badgeX, badgeY] = road.badge;
      const color = roads[car.destination_lane].color;
      roundRect(ctx, x + badgeX - 8, y + badgeY - 8, 16, 16, 4, "#19262d");
      text(ctx, car.destination_lane, x + badgeX, y + badgeY + 0.5, color, "750 12px system-ui", "center");
    }
  }

  if (route) {
    const [x, y, angle] = positionOnRoute(route, progress);
    drawCar(x, y, angle, amber);
  }
}

function node(tag, value, className) {
  const element = document.createElement(tag);
  if (value) element.textContent = value;
  if (className) element.className = className;
  return element;
}

function setText(element, value) {
  if (element.textContent !== value) element.textContent = value;
}

function laneText(lane, className) {
  const element = node("span", lane, className);
  element.dataset.lane = lane;
  return element;
}

function routeBadge(from, to) {
  const badge = node("span", "", "route");
  badge.setAttribute("role", "img");
  badge.setAttribute("aria-label", `Lane ${from} to lane ${to}`);
  badge.append(laneText(from), node("span", "→", "route-arrow"), laneText(to));
  return badge;
}

const laneViews = new Map();

function renderLane(light, demo) {
  let view = laneViews.get(light.lane);
  if (!view) {
    const card = node("section", "", "lane");
    const heading = node("div", "", "lane-header");
    const identity = node("div", "", "lane-identity");
    const badge = laneText(light.lane, "lane-badge");
    badge.setAttribute("aria-hidden", "true");
    const name = node("h3", `Lane ${light.lane} · ${roads[light.lane].name}`);
    identity.append(badge, name);
    const signal = node("span", "", "signal");
    heading.append(identity, signal);

    const connection = node("p", "", "connection");
    const queueLabel = node("p", "", "queue-label");
    const count = node("span");
    const exitLabel = node("span", "Exit lane");
    queueLabel.append(count, exitLabel);
    const queue = node("ul", "", "queue-list");
    queue.setAttribute("aria-label", `Lane ${light.lane} queued vehicles and destinations`);
    card.append(heading, connection, queueLabel, queue);
    get("lanes").append(card);
    view = {signal, connection, count, exitLabel, queue};
    laneViews.set(light.lane, view);
  }

  const {signal, connection, count, exitLabel, queue} = view;
  signal.dataset.color = light.color;
  setText(signal, light.color);
  connection.dataset.status = light.connection;
  setText(connection, `${light.connection} · ${demo ? "Simulated light" : light.ip}`);
  setText(count, `${light.waiting} queued`);
  exitLabel.hidden = light.waiting === 0;

  const queueKey = JSON.stringify(light.cars);
  if (queueKey !== view.queueKey) {
    view.queueKey = queueKey;
    const scroll = queue.scrollTop;
    queue.replaceChildren(...light.cars.map(car => {
      const row = node("li", "", "queue-row");
      const destination = laneText(car.destination_lane, "destination");
      destination.setAttribute("role", "img");
      destination.setAttribute("aria-label", `Destination lane ${car.destination_lane}`);
      row.append(node("span", car.car), destination);
      return row;
    }));
    queue.scrollTop = scroll;
    if (queue.scrollHeight > queue.clientHeight) queue.tabIndex = 0;
    else queue.removeAttribute("tabindex");
  }
}

let crossingTrip;
let historyKey;

function renderStatus(state) {
  setText(get("coordinator"), `${state.demo ? "Local demo" : "Coordinator"} · ${state.coordinator}`);
  const timing = get("timing");
  setText(timing, `${state.crossing_seconds} s crossing time`);
  timing.hidden = false;
  setText(get("waiting"), String(state.lanes.reduce((sum, light) => sum + light.waiting, 0)));
  setText(get("total"), String(state.total_crossed));

  const crossing = get("crossing");
  setText(crossing, state.current_car || "None");
  crossing.dataset.active = Boolean(state.current_car);
  if (crossingTrip !== state.current_trip) {
    crossingTrip = state.current_trip;
    get("crossing-route").replaceChildren(
      ...(crossingTrip ? [routeBadge(state.current_lane, state.current_destination_lane)] : []));
  }

  const phase = get("phase");
  const green = state.lanes.find(light => light.color === "GREEN");
  const missing = state.lanes.some(light => light.connection !== "Online");
  phase.dataset.color = missing ? "" : green ? "GREEN" : "RED";
  if (missing) setText(phase, "Waiting for light connections");
  else if (green) setText(phase, `Lane ${green.lane} green`);
  else if (state.cooldown > 0) setText(phase, `All red · ${state.cooldown.toFixed(1)} s clearance`);
  else setText(phase, "All red");

  get("lanes").querySelector(".lane-empty")?.remove();
  for (const light of state.lanes) renderLane(light, state.demo);

  const recentKey = JSON.stringify(state.recent);
  if (historyKey !== recentKey) {
    historyKey = recentKey;
    const rows = state.recent.map(item => {
      const row = node("li", "", "history-row");
      row.append(node("span", item.car), routeBadge(item.lane, item.destination_lane));
      return row;
    });
    get("recent").replaceChildren(...(rows.length ? rows : [node("li", "No crossings yet", "empty")]));
  }
}

let snapshot;
let active;
let frame;

function paint(now) {
  frame = undefined;
  if (!active) {
    drawMap(snapshot);
    return;
  }
  const elapsed = (now - active.sampleTime) / 1000;
  const forecast = active.sampleProgress + elapsed / snapshot.crossing_seconds;
  active.progress = Math.min(1, Math.max(active.progress, forecast));
  drawMap(snapshot, active.route, motion.matches ? 0.5 : active.progress);
  if (!motion.matches && active.progress < 1) frame = requestAnimationFrame(paint);
}

function updateMap(state) {
  if (state.current_trip) {
    const previous = active?.trip === state.current_trip ? active : undefined;
    active = {
      trip: state.current_trip,
      route: previous?.route ?? buildRoute(state.current_lane, state.current_destination_lane),
      progress: previous?.progress ?? 0,
      sampleProgress: state.progress,
      sampleTime: performance.now(),
    };
  } else {
    active = undefined;
  }
  snapshot = state;
  if (frame === undefined) frame = requestAnimationFrame(paint);
}

motion.addEventListener("change", () => {
  if (frame === undefined) frame = requestAnimationFrame(paint);
});

async function refresh() {
  const feed = get("feed");
  try {
    const response = await fetch("/state", {signal: AbortSignal.timeout(3000)});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const state = await response.json();
    renderStatus(state);
    updateMap(state);
    setText(feed, state.demo ? "Demo running" : "Live");
    feed.dataset.live = "true";
  } catch {
    setText(feed, "Disconnected · retrying");
    feed.dataset.live = "false";
  } finally {
    setTimeout(refresh, 200);
  }
}

drawMap();
refresh();

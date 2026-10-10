// Cloudflare Worker that starts the Collect iOS Jobs workflow on schedule.
//
// GitHub Actions delivers only a small share of its own cron ticks, so this
// Worker is the off-Mac scheduler. It mirrors scripts/should_kick_collect.py:
// dispatch the latest Kyiv slot once it is LAG_MINUTES old, before 21:00, when
// collect_slots.json does not record it and no Collect run is active.

export const SLOT_HOURS = [8, 14];
export const LAG_MINUTES = 15;
export const LAST_HOUR = 21;
const REPO = "vil4max/ios-vacancy-radar";
const WORKFLOW = "collect.yml";
const API = "https://api.github.com";

export function kyivClock(date) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "Europe/Kyiv",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(date)
      .map((part) => [part.type, part.value]),
  );
  return {
    day: `${parts.year}-${parts.month}-${parts.day}`,
    minutes: Number(parts.hour) * 60 + Number(parts.minute),
  };
}

export function dueSlot(date, slots) {
  const { day, minutes } = kyivClock(date);
  if (minutes >= LAST_HOUR * 60) return null;
  const started = SLOT_HOURS.filter((hour) => minutes >= hour * 60 + LAG_MINUTES);
  if (started.length === 0) return null;
  const slot = started[started.length - 1];
  const done = slots?.days?.[day]?.slots ?? [];
  return done.includes(slot) ? null : { day, slot };
}

async function github(env, path, init = {}) {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "User-Agent": "ios-vacancy-radar-dispatcher",
      "X-GitHub-Api-Version": "2022-11-28",
      ...init.headers,
    },
  });
  if (!response.ok) {
    throw new Error(`GitHub ${init.method ?? "GET"} ${path}: HTTP ${response.status}`);
  }
  return response;
}

async function collectSlots(env) {
  const response = await github(env, `/repos/${REPO}/contents/database/collect_slots.json?ref=main`, {
    headers: { Accept: "application/vnd.github.raw" },
  });
  return response.json();
}

async function activeRuns(env) {
  let count = 0;
  for (const status of ["queued", "in_progress", "pending", "waiting"]) {
    const response = await github(env, `/repos/${REPO}/actions/workflows/${WORKFLOW}/runs?status=${status}&per_page=1`);
    count += (await response.json()).total_count;
  }
  return count;
}

export async function tick(env, now = new Date()) {
  const due = dueSlot(now, await collectSlots(env));
  if (due === null) return "skip: no due slot";
  if ((await activeRuns(env)) > 0) return `skip: Collect already active for ${due.day} ${due.slot}`;
  await github(env, `/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    body: JSON.stringify({ ref: "main" }),
  });
  return `dispatched: ${due.day} slot ${due.slot}`;
}

export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(tick(env, new Date(controller.scheduledTime)).then(console.log));
  },
};

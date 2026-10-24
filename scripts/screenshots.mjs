#!/usr/bin/env node
/**
 * Capture UI screenshots of the three frontends for before/after comparisons.
 *
 * NOTE: Playwright lives outside the repo and isn't installed by npm install.
 * If an earlier install was in a temporary directory that has since been
 * cleared, reinstall it somewhere persistent (see "Playwright" below), e.g.
 * ~/.cache/qna-playwright. On a fresh Ubuntu/WSL machine Chromium also needs
 * system libraries: sudo apt-get install -y libnspr4 libnss3 libasound2t64
 *
 * Expects the backend (http://localhost:8000) and the three Vite dev servers
 * (student 5173, staff 5174, admin 5175) to be running, with seed_demo.py
 * already applied.
 *
 * Setup:
 *   - Uses the first STUDENT and first STAFF netid users enrolled in the
 *     "AI-Assisted Software Development" course. If there are none, it creates
 *     demo_student / demo_staff through the dev netid login, then grants them
 *     access through the admin API (ADMIN_USERNAME / ADMIN_PASSWORD from the
 *     environment or the repo's .env).
 *   - Logs in through each app's real login page (Dev Login for the student
 *     and staff apps, username/password for the admin app).
 *
 * Usage:
 *   node scripts/screenshots.mjs [--prefix before|after] [--theme light|dark] [--apps student,staff,admin] [--out docs/ui]
 *
 * Files are named <prefix>-<app>-<screen>.png, or <prefix>-<app>-<screen>-<theme>.png
 * when --theme is passed explicitly (omit it on branches without theming).
 *
 * Playwright is not a project dependency. Install it somewhere else and point
 * PLAYWRIGHT_DIR at that directory:
 *   npm install --prefix ~/.cache/qna-playwright playwright
 *   npx --prefix ~/.cache/qna-playwright playwright install chromium
 *   PLAYWRIGHT_DIR=~/.cache/qna-playwright node scripts/screenshots.mjs --prefix before
 */

import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const COURSE_NAME = 'AI-Assisted Software Development';
const VIEWPORT = { width: 1440, height: 900 };

const { values: args } = parseArgs({
  options: {
    prefix: { type: 'string', default: 'before' },
    theme: { type: 'string' },
    apps: { type: 'string', default: 'student,staff,admin' },
    out: { type: 'string', default: 'docs/ui' },
  },
});
const THEME = args.theme ?? 'light';
if (!['light', 'dark'].includes(THEME)) {
  throw new Error(`--theme must be light or dark, got '${THEME}'`);
}
const THEME_SUFFIX = args.theme ? `-${THEME}` : '';
const SELECTED_APPS = new Set(args.apps.split(',').map((a) => a.trim()));

const API = (process.env.BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '');
const APPS = {
  student: process.env.STUDENT_URL ?? 'http://localhost:5173',
  staff: process.env.STAFF_URL ?? 'http://localhost:5174',
  admin: process.env.ADMIN_URL ?? 'http://localhost:5175',
};
const OUT_DIR = path.resolve(REPO_ROOT, args.out);

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

function readDotEnv() {
  const file = path.join(REPO_ROOT, '.env');
  if (!fs.existsSync(file)) return {};
  const env = {};
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (m) env[m[1]] = m[2].replace(/^(['"])(.*)\1$/, '$2');
  }
  return env;
}

const dotEnv = readDotEnv();
const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? dotEnv.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? dotEnv.ADMIN_PASSWORD;
if (!ADMIN_PASSWORD) throw new Error('ADMIN_PASSWORD not set (environment or .env)');

async function loadPlaywright() {
  const dir = process.env.PLAYWRIGHT_DIR;
  if (!dir) return import('playwright');
  const require = createRequire(path.join(path.resolve(dir), 'package.json'));
  // CJS named exports aren't always detected via a file URL import; fall back to default.
  const mod = await import(pathToFileURL(require.resolve('playwright')).href);
  return mod.chromium ? mod : mod.default;
}

// ---------------------------------------------------------------------------
// API setup
// ---------------------------------------------------------------------------

async function api(method, urlPath, { token, body } = {}) {
  const res = await fetch(`${API}/api${urlPath}`, {
    method,
    headers: {
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${urlPath} → ${res.status} ${await res.text()}`);
  return res.status === 204 ? null : res.json();
}

async function findEnrolled(adminToken, courseId, role) {
  const users = await api('GET', '/admin/users', { token: adminToken });
  for (const u of users.filter((u) => u.netid && u.role === 'USER')) {
    const detail = await api('GET', `/admin/users/${u.id}`, { token: adminToken });
    if (detail.course_access.some((a) => a.course_id === courseId && a.role === role)) {
      return u.netid;
    }
  }
  return null;
}

async function ensureEnrolled(adminToken, courseId, role, fallbackNetid) {
  const existing = await findEnrolled(adminToken, courseId, role);
  if (existing) {
    console.log(`  ${role}: using existing netid user ${existing}`);
    return existing;
  }
  // Dev netid login creates the user on first sight.
  await api('POST', '/auth/login', { body: { netid: fallbackNetid } });
  const users = await api('GET', '/admin/users', { token: adminToken });
  const user = users.find((u) => u.netid === fallbackNetid);
  await api('POST', `/admin/users/${user.id}/course-access`, {
    token: adminToken,
    body: { course_id: courseId, role },
  });
  console.log(`  ${role}: created ${fallbackNetid} and granted access`);
  return fallbackNetid;
}

async function setup() {
  const { access_token: adminToken } = await api('POST', '/auth/login', {
    body: { username: ADMIN_USERNAME, password: ADMIN_PASSWORD },
  });
  const courses = await api('GET', '/admin/courses', { token: adminToken });
  const course = courses.find((c) => c.name === COURSE_NAME);
  if (!course) throw new Error(`Course '${COURSE_NAME}' not found; run scripts/seed_demo.py`);

  const studentNetid = await ensureEnrolled(adminToken, course.id, 'STUDENT', 'demo_student');
  const staffNetid = await ensureEnrolled(adminToken, course.id, 'STAFF', 'demo_staff');

  // The busiest thread shows the most of the post/answer styling.
  const questions = await api('GET', `/courses/${course.id}/questions`, { token: adminToken });
  if (!questions.length) throw new Error(`No questions in '${COURSE_NAME}'`);
  const question = questions.reduce((a, b) => (b.post_count > a.post_count ? b : a));

  const users = await api('GET', '/admin/users', { token: adminToken });
  const studentUser = users.find((u) => u.netid === studentNetid);

  return { courseId: course.id, questionId: question.id, studentNetid, staffNetid, studentUser };
}

// ---------------------------------------------------------------------------
// Browser
// ---------------------------------------------------------------------------

async function newPage(browser, courseId) {
  const context = await browser.newContext({ viewport: VIEWPORT });
  await context.addInitScript(
    ([theme, courseId]) => {
      localStorage.setItem('theme', theme);
      localStorage.setItem('course_id', String(courseId));
    },
    [THEME, courseId],
  );
  return context.newPage();
}

async function devLogin(page, baseUrl, netid) {
  await page.goto(`${baseUrl}/login`);
  await page.getByPlaceholder('netid').fill(netid);
  await page.getByRole('button', { name: 'Dev Login' }).click();
  await page.waitForURL(/\/questions/);
}

async function passwordLogin(page, baseUrl) {
  await page.goto(`${baseUrl}/login`);
  await page.getByPlaceholder('Username').fill(ADMIN_USERNAME);
  await page.getByPlaceholder('Password').fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: 'Sign In' }).click();
  await page.waitForURL(/\/courses/);
}

async function shoot(page, url, app, screen) {
  await page.goto(url);
  await page.waitForLoadState('networkidle');
  const file = path.join(OUT_DIR, `${args.prefix}-${app}-${screen}${THEME_SUFFIX}.png`);
  await page.screenshot({ path: file });
  console.log(`  ✓ ${path.relative(REPO_ROOT, file)}`);
}

async function main() {
  console.log('Setting up users …');
  const s = await setup();
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const { chromium } = await loadPlaywright();
  const browser = await chromium.launch();
  try {
    console.log(`Capturing (${args.prefix}, ${args.theme ?? 'no theme'}) …`);

    if (SELECTED_APPS.has('student')) {
      const student = await newPage(browser, s.courseId);
      await devLogin(student, APPS.student, s.studentNetid);
      await shoot(student, `${APPS.student}/questions`, 'student', 'board');
      await shoot(student, `${APPS.student}/questions/${s.questionId}`, 'student', 'thread');
    }

    if (SELECTED_APPS.has('staff')) {
      const staff = await newPage(browser, s.courseId);
      await devLogin(staff, APPS.staff, s.staffNetid);
      await shoot(staff, `${APPS.staff}/questions/${s.questionId}`, 'staff', 'thread');
      await shoot(staff, `${APPS.staff}/categories`, 'staff', 'categories');
    }

    if (SELECTED_APPS.has('admin')) {
      const admin = await newPage(browser, s.courseId);
      await passwordLogin(admin, APPS.admin);
      await shoot(admin, `${APPS.admin}/courses`, 'admin', 'courses');
      await shoot(admin, `${APPS.admin}/users/${s.studentUser.id}`, 'admin', 'user');
    }
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

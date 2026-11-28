/**
 * Canonical full-pytest runner.
 *
 * The child's stdout and stderr are file descriptors on a regular log file — never the
 * caller's terminal or pipe. A terminal, agent harness, or captured pipe that stops draining
 * therefore cannot block the pytest controller, and xdist workers cannot idle behind a
 * controller stuck in a terminal write (measured: an hours-long "stall" at ~94% executed).
 *
 * Only bounded output reaches the terminal: a line at start naming the log, a bounded tail of
 * the log, and the exit code at the end — under 4 KiB in total, the smallest pipe buffer on a
 * supported host, so even a dead reader receives the exit code. The full log is the diagnostic
 * record.
 *
 * The suite runs as CI runs it (.github/workflows/pytest.yml): the workers on every test but
 * those marked `alone`, then each `alone` test (a limit on the wall clock) with none beside it,
 * each part with its own log and its share of the tail (PART_TAIL_BYTES). Both parts run, as in
 * CI.
 *
 * Usage: node scripts/run-pytest-full.mjs [extra pytest args]
 *   Extra args follow the canonical args, so a later `-n 0` or a test path narrows both parts
 *   (pytest keeps the last value of a repeated option).
 *
 * `runWithFileSink` is shared with scripts/run-playwright-e2e.mjs, which sinks the Playwright
 * run (and the uvicorn webServer output it relays) the same way.
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { projectPython } from "./project-python.mjs";

export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/**
 * Byte budget for the log tail echoed to the terminal after the child exits.
 *
 * Measured: a 60-line tail of 100-character lines (6 KB) blocked this runner
 * behind a reader that never drained, after the child had already completed — Windows
 * anonymous pipes hold 4 KiB. Everything this runner writes to the terminal for one run
 * (two start lines, the tail header, the tail, the exit line) stays under that, so even a
 * dead reader receives the exit code. Budget is bytes, not lines: lines are also clipped.
 */
export const TAIL_BYTES = 1600;
export const TAIL_LINE_MAX = 200;

/** Log directory: `logs/` at the repo root (gitignored) unless ED_TEST_LOG_DIR moves it. */
export function logDir() {
  return path.resolve(root, process.env.ED_TEST_LOG_DIR || "logs");
}

/** The last lines of `text` that fit in `budget` bytes, each clipped to TAIL_LINE_MAX. */
export function boundedTail(text, budget = TAIL_BYTES) {
  const lines = text.split(/\r?\n/);
  if (lines.length && lines[lines.length - 1] === "") lines.pop();
  const tail = [];
  let bytes = 0;
  for (let i = lines.length - 1; i >= 0; i--) {
    const line =
      lines[i].length > TAIL_LINE_MAX ? lines[i].slice(0, TAIL_LINE_MAX - 1) + "…" : lines[i];
    const size = Buffer.byteLength(line, "utf8") + 1;
    if (bytes + size > budget) break;
    tail.unshift(line);
    bytes += size;
  }
  return { tail, total: lines.length };
}

function printTail(label, logPath, budget) {
  if (budget <= 0) return;
  let text;
  try {
    text = fs.readFileSync(logPath, "utf8");
  } catch (e) {
    console.error(`[${label}] could not read ${logPath}: ${e.message}`);
    return;
  }
  const { tail, total } = boundedTail(text, budget);
  console.log(`[${label}] last ${tail.length} of ${total} log lines:`);
  for (const line of tail) console.log(line);
}

/**
 * Run `cmd args` with stdout+stderr written straight to `logPath` (truncated first).
 * Returns the child's exit code (spawn failure or signal death → 1) after printing at most
 * `tailBytes` of the log. The child's output is never streamed through this process.
 */
export function runWithFileSink(
  label,
  cmd,
  args,
  { logPath, cwd = root, env = process.env, shell = false, tailBytes = TAIL_BYTES },
) {
  fs.mkdirSync(path.dirname(logPath), { recursive: true });
  const fd = fs.openSync(logPath, "w");
  console.log(`[${label}] running ${[cmd, ...args].join(" ")} (full output -> ${logPath})`);
  let result;
  try {
    // Node 24 (DEP0190) warns on an args array under `shell: true` — and that warning
    // would land on the terminal, the one place this runner keeps quiet. A shell command
    // is handed over as the one string the shell will parse anyway.
    result = shell
      ? spawnSync([cmd, ...args].join(" "), { cwd, env, shell: true, stdio: ["ignore", fd, fd] })
      : spawnSync(cmd, args, { cwd, env, stdio: ["ignore", fd, fd] });
  } finally {
    fs.closeSync(fd);
  }
  printTail(label, logPath, tailBytes);
  if (result.error) {
    console.error(`[${label}] could not start ${cmd}: ${result.error.message}`);
  }
  if (result.status === null && result.signal) {
    console.error(`[${label}] terminated by signal ${result.signal}`);
  }
  // a run that could not start, or ended by a signal, has no exit status of its own: it failed
  const code = result.error || result.status === null ? 1 : result.status;
  console.log(`[${label}] exit code ${code}`); // the start line names the log
  return code;
}

/** pytest's exit code when a run's selection holds no test (pytest's ExitCode.NO_TESTS_COLLECTED). */
const NO_TESTS_COLLECTED = 5;

/**
 * Each part's tail: two parts' tails, and the second part's own start and exit lines in the
 * third share, keep the run's terminal output inside one part's budget.
 */
const PART_TAIL_BYTES = Math.floor(TAIL_BYTES / 3);

/**
 * The suite's exit code from its parts' codes: the first part's failure, else 0; a part whose
 * selection held no test neither passed nor failed, and a run where no part held one is
 * NO_TESTS_COLLECTED, as pytest says of such a run.
 */
function suiteCode(codes) {
  const failed = codes.filter((c) => c !== 0 && c !== NO_TESTS_COLLECTED);
  if (failed.length) return failed[0];
  return codes.every((c) => c === NO_TESTS_COLLECTED) ? NO_TESTS_COLLECTED : 0;
}

const invokedDirectly =
  process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (invokedDirectly) {
  // One worker per processor the machine has, as CI pins it (.github/workflows/pytest.yml):
  // xdist's `-n auto` reads fewer.
  const workers = String(os.availableParallelism());
  const parts = [
    {
      label: "pytest",
      args: ["-n", workers, "--dist", "loadfile", "--durations=20", "-m", "not alone"],
      log: "test_pytest_last.log",
    },
    {
      label: "pytest alone",
      args: ["--durations=1", "-m", "alone"],
      log: "test_pytest_alone_last.log",
    },
  ];
  const codes = parts.map(({ label, args, log }) =>
    runWithFileSink(
      label,
      projectPython(root),
      ["-m", "pytest", ...args, ...process.argv.slice(2)],
      {
        logPath: path.join(logDir(), log),
        tailBytes: PART_TAIL_BYTES,
      },
    ),
  );
  process.exit(suiteCode(codes));
}

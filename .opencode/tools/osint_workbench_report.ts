import { tool } from "@opencode-ai/plugin"
import fs from "node:fs"
import path from "node:path"

const FALLBACK_ROOT = "/mnt/c/users/aarav/OneDrive/Documents/GitHub/PhotoGeoOSINT"

function resolveRoot() {
  if (process.env.PHOTO_GEO_OSINT_ROOT) {
    return process.env.PHOTO_GEO_OSINT_ROOT
  }
  const relativeRoot = path.resolve(import.meta.dir, "..", "..")
  return fs.existsSync(path.join(relativeRoot, "osint_workbench_report.py")) ? relativeRoot : FALLBACK_ROOT
}

function resolvePython(root: string) {
  const localPython = path.join(root, ".venv", "bin", "python")
  return fs.existsSync(localPython) ? localPython : "python3"
}

async function run(argv: string[]) {
  const proc = Bun.spawn(argv, {
    stdout: "pipe",
    stderr: "pipe",
    cwd: resolveRoot(),
  })
  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ])

  if (exitCode !== 0) {
    throw new Error((stderr || stdout || `Command failed with exit code ${exitCode}`).trim())
  }

  return stdout.trim()
}

export default tool({
  description: "Generate a combined OSINT challenge report from photo, file, text, username, and identity pivots.",
  args: {
    input: tool.schema.string().default("").describe("Optional path, Windows path, or URL"),
    text: tool.schema.string().default("").describe("Optional raw clue text"),
    username: tool.schema.string().default("").describe("Optional known username or handle"),
    challenge_name: tool.schema.string().default("").describe("Optional challenge name"),
    challenge_description: tool.schema.string().default("").describe("Optional challenge description"),
    use_grok: tool.schema.boolean().default(false).describe("Optionally run Grok within the photo pipeline when configured"),
    format: tool.schema.enum(["json", "markdown"]).default("json").describe("Output format"),
  },
  async execute(args) {
    const root = resolveRoot()
    const script = path.join(root, "osint_workbench_report.py")
    if (!fs.existsSync(script)) {
      throw new Error(`Missing helper script: ${script}`)
    }

    const command = [resolvePython(root), script, "--format", args.format]
    if (args.input) command.push("--input", args.input)
    if (args.text) command.push("--text", args.text)
    if (args.username) command.push("--username", args.username)
    if (args.challenge_name) command.push("--challenge-name", args.challenge_name)
    if (args.challenge_description) command.push("--challenge-description", args.challenge_description)
    if (args.use_grok) command.push("--use-grok")
    return run(command)
  },
})

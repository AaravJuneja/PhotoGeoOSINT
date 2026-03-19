import { tool } from "@opencode-ai/plugin"
import fs from "node:fs"
import path from "node:path"

const FALLBACK_ROOT = "/mnt/c/users/aarav/OneDrive/Documents/GitHub/PhotoGeoOSINT"

function resolveRoot() {
  if (process.env.PHOTO_GEO_OSINT_ROOT) {
    return process.env.PHOTO_GEO_OSINT_ROOT
  }
  const relativeRoot = path.resolve(import.meta.dir, "..", "..")
  return fs.existsSync(path.join(relativeRoot, "osint_text_extract.py")) ? relativeRoot : FALLBACK_ROOT
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
  description: "Extract OSINT-ready pivots from raw clue text or challenge descriptions.",
  args: {
    text: tool.schema.string().describe("Raw clue text or challenge description"),
    challenge_name: tool.schema.string().default("").describe("Optional challenge name"),
  },
  async execute(args) {
    const root = resolveRoot()
    const script = path.join(root, "osint_text_extract.py")
    if (!fs.existsSync(script)) {
      throw new Error(`Missing helper script: ${script}`)
    }

    const command = [resolvePython(root), script, "--text", args.text]
    if (args.challenge_name) command.push("--challenge-name", args.challenge_name)
    return run(command)
  },
})

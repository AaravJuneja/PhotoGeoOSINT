import { tool } from "@opencode-ai/plugin"
import fs from "node:fs"
import path from "node:path"

const FALLBACK_ROOT = "/mnt/c/users/aarav/OneDrive/Documents/GitHub/PhotoGeoOSINT"

function resolveRoot() {
  if (process.env.PHOTO_GEO_OSINT_ROOT) {
    return process.env.PHOTO_GEO_OSINT_ROOT
  }
  const relativeRoot = path.resolve(import.meta.dir, "..", "..")
  return fs.existsSync(path.join(relativeRoot, "grok_search_enrich.py")) ? relativeRoot : FALLBACK_ROOT
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
  description: "Optionally use xAI Grok web/X search for extra real-time OSINT context.",
  args: {
    prompt: tool.schema.string().describe("Research prompt for Grok web and X search"),
    challenge_name: tool.schema.string().default("").describe("Optional CTF challenge name"),
    challenge_description: tool.schema.string().default("").describe("Optional CTF challenge description"),
    enable_x_search: tool.schema.boolean().default(true).describe("Also search X posts via xAI x_search"),
    enable_image_understanding: tool.schema.boolean().default(true).describe("Allow Grok search tools to analyze images they encounter"),
  },
  async execute(args) {
    const root = resolveRoot()
    const script = path.join(root, "grok_search_enrich.py")
    if (!fs.existsSync(script)) {
      throw new Error(`Missing helper script: ${script}`)
    }

    const command = [resolvePython(root), script, "--prompt", args.prompt]
    if (args.challenge_name) command.push("--challenge-name", args.challenge_name)
    if (args.challenge_description) command.push("--challenge-description", args.challenge_description)
    if (!args.enable_x_search) command.push("--disable-x-search")
    if (!args.enable_image_understanding) command.push("--disable-image-understanding")
    return run(command)
  },
})

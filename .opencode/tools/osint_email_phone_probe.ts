import { tool } from "@opencode-ai/plugin"
import fs from "node:fs"
import path from "node:path"

const FALLBACK_ROOT = "/mnt/c/users/aarav/OneDrive/Documents/GitHub/PhotoGeoOSINT"

function resolveRoot() {
  if (process.env.PHOTO_GEO_OSINT_ROOT) {
    return process.env.PHOTO_GEO_OSINT_ROOT
  }
  const relativeRoot = path.resolve(import.meta.dir, "..", "..")
  return fs.existsSync(path.join(relativeRoot, "osint_email_phone_probe.py")) ? relativeRoot : FALLBACK_ROOT
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
  description: "Normalize and enrich emails and phone numbers with free local-first probes.",
  args: {
    text: tool.schema.string().default("").describe("Raw text containing emails or phone numbers"),
    email: tool.schema.string().default("").describe("Specific email to probe"),
    phone: tool.schema.string().default("").describe("Specific phone number to probe"),
    default_region: tool.schema.string().default("US").describe("Default region hint for phone parsing without a country code"),
  },
  async execute(args) {
    const root = resolveRoot()
    const script = path.join(root, "osint_email_phone_probe.py")
    if (!fs.existsSync(script)) {
      throw new Error(`Missing helper script: ${script}`)
    }

    const command = [resolvePython(root), script, "--default-region", args.default_region]
    if (args.text) command.push("--text", args.text)
    if (args.email) command.push("--email", args.email)
    if (args.phone) command.push("--phone", args.phone)
    return run(command)
  },
})

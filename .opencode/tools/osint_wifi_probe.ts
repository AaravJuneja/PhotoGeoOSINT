import { tool } from "@opencode-ai/plugin"
import fs from "node:fs"
import path from "node:path"

const FALLBACK_ROOT = "/mnt/c/users/aarav/OneDrive/Documents/GitHub/PhotoGeoOSINT"

function resolveRoot() {
  if (process.env.PHOTO_GEO_OSINT_ROOT) {
    return process.env.PHOTO_GEO_OSINT_ROOT
  }
  const relativeRoot = path.resolve(import.meta.dir, "..", "..")
  return fs.existsSync(path.join(relativeRoot, "osint_wifi_probe.py")) ? relativeRoot : FALLBACK_ROOT
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
  description: "Run free local-first Wi-Fi and BSSID probing from text, SSIDs, and MAC addresses.",
  args: {
    text: tool.schema.string().default("").describe("Raw text containing SSIDs, BSSIDs, or Wi-Fi QR payloads"),
    bssid: tool.schema.string().default("").describe("Specific BSSID or MAC address to probe"),
    ssid: tool.schema.string().default("").describe("Specific SSID to probe"),
  },
  async execute(args) {
    const root = resolveRoot()
    const script = path.join(root, "osint_wifi_probe.py")
    if (!fs.existsSync(script)) {
      throw new Error(`Missing helper script: ${script}`)
    }

    const command = [resolvePython(root), script]
    if (args.text) command.push("--text", args.text)
    if (args.bssid) command.push("--bssid", args.bssid)
    if (args.ssid) command.push("--ssid", args.ssid)
    return run(command)
  },
})

# fake-llama.ps1 — local fake llama-server (OpenAI-compatible) for router tests.
# No GPU, no model. Responds to POST /v1/chat/completions with a fixed action.
#
#   pwsh -NoProfile -File fake-llama.ps1                 # returns GIT_STATUS
#   pwsh -NoProfile -File fake-llama.ps1 -Action BLOCKED # forces BLOCKED reply
#
# Note (Windows): System.Net.HttpListener may require an admin URL ACL for
# non-localhost prefixes; 127.0.0.1 is used, which normally works. If you see an
# AccessDenied, run the router against your real llama-server instead.

[CmdletBinding()]
param([int]$Port = 8333, [string]$Action = 'GIT_STATUS')

$ErrorActionPreference = 'Stop'
$listener = [System.Net.HttpListener]::new()
$listener.Prefixes.Add("http://127.0.0.1:$Port/")
$listener.Start()
Write-Host "Fake llama listening on http://127.0.0.1:$Port/  (action=$Action)  Ctrl+C to stop."

$count = 0
while ($listener.IsListening) {
    try {
        $ctx = $listener.GetContext()
        $count++
        Write-Host "[$count] request: $($ctx.Request.HttpMethod) $($ctx.Request.Url.AbsolutePath)"
        $resp = '{"choices":[{"message":{"content":"' + $Action + '"}}]}'
        $buf = [System.Text.Encoding]::UTF8.GetBytes($resp)
        $ctx.Response.StatusCode = 200
        $ctx.Response.ContentType = 'application/json; charset=utf-8'
        $ctx.Response.ContentLength64 = $buf.Length
        $ctx.Response.OutputStream.Write($buf, 0, $buf.Length)
        $ctx.Response.OutputStream.Close()
        $ctx.Response.Close()
    }
    catch {
        Write-Host "fake-llama error: $($_.Exception.Message)"
        break
    }
}
$listener.Stop()

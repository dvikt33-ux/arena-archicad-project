# arena-common.ps1 — shared helpers for Arena Bridge v2 (bridge + router).
# Dot-source this file from arena-bridge-v2.ps1 and arena-qwen-router-v2.ps1.

# ---- action IDs (the ONLY things Qwen may emit) ----
$script:ActionIds = @('GIT_VERSION', 'GIT_STATUS', 'GIT_DIFF', 'GIT_LOG10')

# ---- legacy v1 paths (used only to seed the sequence once) ----
# $env:USERPROFILE exists on Windows; fall back to $env:HOME elsewhere (tests).
$script:UserProfile = $env:USERPROFILE
if ([string]::IsNullOrWhiteSpace($script:UserProfile)) { $script:UserProfile = $env:HOME }
if ([string]::IsNullOrWhiteSpace($script:UserProfile)) { $script:UserProfile = [System.IO.Path]::GetTempPath() }
# Two Join-Path calls: Windows PowerShell 5.1 treats '\' in the child as a
# separator, PowerShell 7 on Linux does too, but a single child with '\' is
# easy to get wrong. Keep the v1 files exactly where v1 wrote them.
$script:LegacyStateFile = Join-Path (Join-Path $script:UserProfile 'Documents') 'arena-bridge-last-task.txt'
$script:LegacyTaskFile  = Join-Path (Join-Path $script:UserProfile 'Documents') 'arena-bridge-task.txt'

function New-Dirs {
    param([string]$ArenaRoot)
    $paths = @(
        $ArenaRoot,
        (Join-Path $ArenaRoot 'inbox'),
        (Join-Path $ArenaRoot 'outbox'),
        (Join-Path $ArenaRoot 'results'),
        (Join-Path $ArenaRoot 'inbox\.done'),
        (Join-Path $ArenaRoot 'outbox\.dead'),
        (Join-Path $ArenaRoot 'held'),
        (Join-Path $ArenaRoot 'approve'),
        (Join-Path $ArenaRoot 'mailbox-staging'),
        (Join-Path $ArenaRoot 'reservations')
    )
    foreach ($p in $paths) {
        if (-not (Test-Path -LiteralPath $p)) {
            New-Item -ItemType Directory -Path $p -Force | Out-Null
        }
    }
}

function Write-FileAtomic {
    param([Parameter(Mandatory = $true)][string]$Path, [string]$Text = '')
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $tmp = Join-Path $dir ('~' + [guid]::NewGuid().ToString('N') + '.tmp')
    $enc = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($tmp, $Text, $enc)
    try {
        if (Test-Path -LiteralPath $Path) {
            # Atomic replace (Windows .NET Framework). On .NET Core / Unix this
            # throws on a null backup name, so fall back to Move-Item -Force,
            # which is rename-based and still atomic on the same volume.
            try {
                [System.IO.File]::Replace($tmp, $Path, $null)
            }
            catch {
                Move-Item -LiteralPath $tmp -Destination $Path -Force
            }
        }
        else {
            Move-Item -LiteralPath $tmp -Destination $Path -Force
        }
    }
    catch {
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
        throw
    }
}

function Test-OriginMatches {
    param([string]$Origin, [string]$Repo)
    $o = $Origin.Trim()
    $o = $o -replace '\.git/?$', ''
    $o = $o -replace '^https?://', ''
    $o = $o -replace '^ssh://', ''
    $o = $o -replace '^git@', ''
    $o = $o -replace '^github\.com[:/]', ''
    $o = $o.TrimEnd('/')
    return ($o -ieq $Repo)
}

function Read-State {
    # Returns @{ last_seq = <int>; tasks = @{ "<seq>" = @{...} } }.
    # Throws on corrupt/empty/invalid state — callers must fail closed.
    param([string]$StatePath)
    if (-not (Test-Path -LiteralPath $StatePath)) {
        return @{ last_seq = 0; tasks = @{} }
    }
    $raw = Get-Content -LiteralPath $StatePath -Raw -ErrorAction Stop
    if ([string]::IsNullOrWhiteSpace($raw)) { throw 'state file is empty' }
    $s = $null
    try {
        $s = $raw | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "state file is corrupt: $($_.Exception.Message)"
    }
    if ($null -eq $s -or ($s.PSObject.Properties.Name -notcontains 'last_seq')) {
        throw 'state schema invalid (missing last_seq)'
    }
    $st = @{ last_seq = [int]$s.last_seq; tasks = @{}; mailbox = @{ seen = @{}; rejected_seqs = @(); remote_files = @{} } }
    if ($s.PSObject.Properties.Name -notcontains 'tasks') { return $st }
    foreach ($p in $s.tasks.PSObject.Properties) {
        $v = $p.Value
        $names = $v.PSObject.Properties.Name
        $st.tasks[$p.Name] = @{
            action      = if ($names -contains 'action')      { $v.action }      else { '' }
            state       = if ($names -contains 'state')       { $v.state }       else { '' }
            status      = if ($names -contains 'status')      { $v.status }      else { '' }
            exit        = if ($names -contains 'exit')        { $v.exit }        else { $null }
            result_file = if ($names -contains 'result_file') { $v.result_file } else { '' }
            comment_id  = if ($names -contains 'comment_id')  { $v.comment_id }  else { $null }
            reason      = if ($names -contains 'reason')      { $v.reason }      else { '' }
            pid         = if ($names -contains 'pid')         { $v.pid }         else { $null }
            started     = if ($names -contains 'started')     { $v.started }     else { '' }
            updated     = if ($names -contains 'updated')     { $v.updated }     else { '' }
            task_id     = if ($names -contains 'task_id')     { [string]$v.task_id } else { '' }
            source      = if ($names -contains 'source')      { [string]$v.source } else { '' }
        }
    }
    if ($s.PSObject.Properties.Name -contains 'mailbox' -and $null -ne $s.mailbox) {
        $mb = $s.mailbox
        $mbNames = @($mb.PSObject.Properties.Name)
        if ($mbNames -contains 'seen' -and $null -ne $mb.seen) {
            foreach ($sp in @($mb.seen.PSObject.Properties)) {
                $sv = $sp.Value
                $sn = @($sv.PSObject.Properties.Name)
                $st.mailbox.seen[$sp.Name] = @{
                    seq         = if ($sn -contains 'seq') { $sv.seq } else { $null }
                    disposition = if ($sn -contains 'disposition') { [string]$sv.disposition } else { '' }
                    reason      = if ($sn -contains 'reason') { [string]$sv.reason } else { '' }
                    action      = if ($sn -contains 'action') { [string]$sv.action } else { '' }
                    content_sha = if ($sn -contains 'content_sha') { [string]$sv.content_sha } else { '' }
                    body_sha    = if ($sn -contains 'body_sha') { [string]$sv.body_sha } else { '' }
                }
            }
        }
        if ($mbNames -contains 'rejected_seqs' -and $null -ne $mb.rejected_seqs) {
            $rawSeqs = $mb.rejected_seqs
            $items = @()
            if ($rawSeqs -is [System.Array]) { $items = @($rawSeqs) } else { $items = @($rawSeqs) }
            foreach ($item in $items) {
                $text = [string]$item
                if ($text -match '^[1-9][0-9]{0,8}$') { $st.mailbox.rejected_seqs += [int]$text }
            }
        }
        if ($mbNames -contains 'remote_files' -and $null -ne $mb.remote_files) {
            foreach ($rp in @($mb.remote_files.PSObject.Properties)) {
                $rv = $rp.Value
                if ($null -eq $rv) { continue }
                $rn = @($rv.PSObject.Properties.Name)
                $exec = 0
                if ($rn -contains 'exec_seq' -and ("$($rv.exec_seq)" -match '^[0-9]+$')) { $exec = [int]$rv.exec_seq }
                $st.mailbox.remote_files[$rp.Name] = @{
                    sha         = if ($rn -contains 'sha') { [string]$rv.sha } else { '' }
                    disposition = if ($rn -contains 'disposition') { [string]$rv.disposition } else { '' }
                    task_id     = if ($rn -contains 'task_id') { [string]$rv.task_id } else { '' }
                    exec_seq    = $exec
                }
            }
        }
    }
    return $st
}

function Save-State {
    param([string]$StatePath, $State)
    $seen = [ordered]@{}
    $rejected = @()
    $remote = [ordered]@{}
    if ($State.mailbox) {
        if ($State.mailbox.seen) {
            foreach ($k in @($State.mailbox.seen.Keys)) { $seen[$k] = $State.mailbox.seen[$k] }
        }
        if ($State.mailbox.rejected_seqs) { $rejected = @($State.mailbox.rejected_seqs) }
        if ($State.mailbox.remote_files) {
            foreach ($k in @($State.mailbox.remote_files.Keys)) { $remote[$k] = $State.mailbox.remote_files[$k] }
        }
    }
    $obj = [ordered]@{
        last_seq = [int]$State.last_seq
        tasks    = [ordered]@{}
        mailbox  = [ordered]@{ seen = $seen; rejected_seqs = $rejected; remote_files = $remote }
    }
    foreach ($k in @($State.tasks.Keys)) {
        $obj.tasks[$k] = $State.tasks[$k]
    }
    $json = $obj | ConvertTo-Json -Depth 12 -Compress
    Write-FileAtomic $StatePath $json
}

function ConvertTo-NativeArgument {
    # CommandLineToArgvW quoting. Not a shell. A quote or backslash stays data.
    param([string]$Text)
    if ($null -eq $Text) { $Text = '' }
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    $slashes = 0
    foreach ($ch in $Text.ToCharArray()) {
        if ($ch -eq '\') {
            $slashes++
            continue
        }
        if ($ch -eq '"') {
            if ($slashes -gt 0) { [void]$sb.Append('\', ($slashes * 2)) }
            [void]$sb.Append('\')
            [void]$sb.Append('"')
            $slashes = 0
            continue
        }
        if ($slashes -gt 0) {
            [void]$sb.Append('\', $slashes)
            $slashes = 0
        }
        [void]$sb.Append($ch)
    }
    if ($slashes -gt 0) { [void]$sb.Append('\', ($slashes * 2)) }
    [void]$sb.Append('"')
    return $sb.ToString()
}

function Resolve-NativeCommandPath {
    # A fixed command name already on PATH. Never a remote string and never a path.
    param([string]$Command)
    if ($Command -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$') { return '' }
    $found = @(Get-Command -Name $Command -CommandType Application -ErrorAction SilentlyContinue)
    if ($found.Count -lt 1) { return '' }
    $path = [string]$found[0].Path
    if ([string]::IsNullOrWhiteSpace($path)) { $path = [string]$found[0].Source }
    if ([string]::IsNullOrWhiteSpace($path)) { return '' }
    if ($path.IndexOf([char]0) -ge 0) { return '' }
    if (-not (Test-Path -LiteralPath $path)) { return '' }
    return $path
}

function Stop-NativeProcessTree {
    # Timeout must kill the spawned process and its children. $ps.Stop() does not
    # do that on Windows PowerShell 5.1: it waits for gh.cmd / cmd / powershell.
    param($Proc)
    if ($null -eq $Proc) { return }
    $procId = 0
    try { $procId = [int]$Proc.Id } catch { return }
    try {
        $killTree = $Proc.GetType().GetMethod('Kill', [type[]]@([bool]))
        if ($null -ne $killTree) {
            $killTree.Invoke($Proc, ([object[]]@($true))) | Out-Null
        }
    }
    catch { }
    $alive = $false
    try { $alive = -not $Proc.HasExited } catch { $alive = $false }
    if ($alive -and $env:OS -eq 'Windows_NT' -and $procId -gt 0) {
        $killer = ''
        if (-not [string]::IsNullOrWhiteSpace($env:SystemRoot)) {
            $killer = Join-Path $env:SystemRoot 'System32\taskkill.exe'
        }
        if (-not [string]::IsNullOrWhiteSpace($killer) -and (Test-Path -LiteralPath $killer)) {
            $kp = $null
            try {
                $ks = New-Object System.Diagnostics.ProcessStartInfo
                $ks.FileName = $killer
                $ks.Arguments = '/F /T /PID ' + $procId
                $ks.UseShellExecute = $false
                $ks.CreateNoWindow = $true
                $ks.RedirectStandardOutput = $true
                $ks.RedirectStandardError = $true
                $kp = [System.Diagnostics.Process]::Start($ks)
                if ($null -ne $kp) { $null = $kp.WaitForExit(3000) }
            }
            catch { }
            finally {
                if ($null -ne $kp) { try { $kp.Dispose() } catch { } }
            }
        }
    }
    try { $alive = -not $Proc.HasExited } catch { $alive = $false }
    if ($alive) {
        try { $Proc.Kill() } catch { }
    }
}

function Invoke-NativeTimed {
    # Fixed executable plus argv. No remote shell string. On timeout the process
    # tree is killed and the caller gets 124 without waiting for the child.
    param([string]$Command, [string[]]$ArgumentList, [int]$TimeoutMs = 30000)
    if ($TimeoutMs -lt 1000) { $TimeoutMs = 1000 }
    if ($TimeoutMs -gt 60000) { $TimeoutMs = 60000 }
    $exePath = Resolve-NativeCommandPath $Command
    if ([string]::IsNullOrWhiteSpace($exePath)) {
        return [pscustomobject]@{ Code = 1; Text = '' }
    }
    $argsSafe = @()
    if ($null -ne $ArgumentList) {
        foreach ($item in $ArgumentList) {
            $text = [string]$item
            if ($text.IndexOf([char]0) -ge 0 -or $text.IndexOf([char]10) -ge 0 -or $text.IndexOf([char]13) -ge 0) {
                return [pscustomobject]@{ Code = 1; Text = '' }
            }
            $argsSafe += $text
        }
    }
    $ext = [System.IO.Path]::GetExtension($exePath).ToLowerInvariant()
    $batch = ($ext -eq '.cmd' -or $ext -eq '.bat')
    $fileName = $exePath
    $argumentString = ''
    if ($batch) {
        if ($env:OS -ne 'Windows_NT') { return [pscustomobject]@{ Code = 1; Text = '' } }
        if ($exePath.IndexOf('"') -ge 0) { return [pscustomobject]@{ Code = 1; Text = '' } }
        $cmdExe = ''
        if (-not [string]::IsNullOrWhiteSpace($env:SystemRoot)) {
            $cmdExe = Join-Path $env:SystemRoot 'System32\cmd.exe'
        }
        if ([string]::IsNullOrWhiteSpace($cmdExe) -or -not (Test-Path -LiteralPath $cmdExe)) {
            return [pscustomobject]@{ Code = 1; Text = '' }
        }
        $fileName = $cmdExe
        # cmd /s strips one leading and one trailing quote. The inner quotes stay.
        # Percent is doubled so cmd does not expand a path as an environment variable.
        $inner = ConvertTo-NativeArgument ($exePath.Replace('%', '%%'))
        foreach ($arg in $argsSafe) {
            if ($arg.IndexOf('"') -ge 0) { return [pscustomobject]@{ Code = 1; Text = '' } }
            $inner = $inner + ' ' + (ConvertTo-NativeArgument ($arg.Replace('%', '%%')))
        }
        $argumentString = '/d /s /c "' + $inner + '"'
    }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $fileName
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    try {
        $utf8 = New-Object System.Text.UTF8Encoding $false
        $psi.StandardOutputEncoding = $utf8
        $psi.StandardErrorEncoding = $utf8
    }
    catch { }
    if ($batch) {
        $psi.Arguments = $argumentString
    }
    else {
        $usedList = $false
        $argProp = $psi.GetType().GetProperty('ArgumentList')
        if ($null -ne $argProp) {
            $list = $argProp.GetValue($psi, $null)
            if ($null -ne $list) {
                foreach ($arg in $argsSafe) { [void]$list.Add($arg) }
                $usedList = $true
            }
        }
        if (-not $usedList) {
            $parts = @()
            foreach ($arg in $argsSafe) { $parts += (ConvertTo-NativeArgument $arg) }
            $psi.Arguments = ($parts -join ' ')
        }
    }
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    try {
        $started = $false
        try { $started = $proc.Start() } catch { $started = $false }
        if (-not $started) { return [pscustomobject]@{ Code = 1; Text = '' } }
        $outTask = $proc.StandardOutput.ReadToEndAsync()
        $errTask = $proc.StandardError.ReadToEndAsync()
        $exited = $false
        try { $exited = $proc.WaitForExit($TimeoutMs) } catch { $exited = $false }
        if (-not $exited) {
            Stop-NativeProcessTree $proc
            try { $null = $proc.WaitForExit(2000) } catch { }
            try { $null = $outTask.Wait(500) } catch { }
            try { $null = $errTask.Wait(500) } catch { }
            return [pscustomobject]@{ Code = 124; Text = '' }
        }
        try { $null = $proc.WaitForExit() } catch { }
        try { $null = $outTask.Wait(2000) } catch { }
        try { $null = $errTask.Wait(2000) } catch { }
        $text = ''
        try { $text = [string]$outTask.Result } catch { $text = '' }
        $errText = ''
        try { $errText = [string]$errTask.Result } catch { $errText = '' }
        if (-not [string]::IsNullOrEmpty($errText)) {
            if ([string]::IsNullOrEmpty($text)) { $text = $errText }
            else { $text = $text + "`n" + $errText }
        }
        $code = 1
        try { $code = [int]$proc.ExitCode } catch { $code = 1 }
        return [pscustomobject]@{ Code = $code; Text = $text.Trim() }
    }
    catch {
        try { Stop-NativeProcessTree $proc } catch { }
        return [pscustomobject]@{ Code = 1; Text = '' }
    }
    finally {
        try { $proc.StandardOutput.Close() } catch { }
        try { $proc.StandardError.Close() } catch { }
        try { $proc.Dispose() } catch { }
    }
}

function Get-SeedLastSeq {
    # One-time seed from the v1 state file (last completed task id).
    param([string]$LegacyStateFile)
    if (-not (Test-Path -LiteralPath $LegacyStateFile)) { return 0 }
    $raw = "$(Get-Content -LiteralPath $LegacyStateFile -Raw -ErrorAction SilentlyContinue)".Trim()
    $n = 0
    if ($raw -match '^\d+$') { $n = [int]$raw }
    return $n
}
function Get-SeqLeaseSeconds {
    # A reservation older than this, with no inbox file, is abandoned.
    # It is not executed. Default 120 seconds. Tests can shorten it.
    $raw = [Environment]::GetEnvironmentVariable('ARENA_SEQ_LEASE_SEC')
    if ($raw -match '^[0-9]+$') {
        $n = [int]$raw
        if ($n -gt 3600) { return 3600 }
        return $n
    }
    return 120
}

function Test-ReservationExpired {
    param([string]$Path, [int]$LeaseSeconds)
    # Unreadable or undated reservations are expired so a corrupt lease cannot
    # block the queue. Abandonment is REJECTED, never execution.
    $raw = ''
    try { $raw = [System.IO.File]::ReadAllText($Path) } catch { return $true }
    $m = [regex]::Match($raw, '"created"\s*:\s*"([^"]+)"')
    if (-not $m.Success) { return $true }
    $parsed = [datetime]::MinValue
    $styles = [System.Globalization.DateTimeStyles]::AdjustToUniversal -bor [System.Globalization.DateTimeStyles]::AssumeUniversal
    $ok = [datetime]::TryParseExact(
        $m.Groups[1].Value,
        'yyyy-MM-ddTHH:mm:ssZ',
        [System.Globalization.CultureInfo]::InvariantCulture,
        $styles,
        [ref]$parsed)
    if (-not $ok) { return $true }
    $age = ([datetime]::UtcNow - $parsed.ToUniversalTime()).TotalSeconds
    if ($age -ge $LeaseSeconds) { return $true }
    return $false
}

function Reserve-TaskSeq {
    # One allocator for the router and mailbox import.
    # The mailbox producer must not call this. A remote id is not an execution slot.
    # mailbox-staging is not scanned. A leftover numeric staging file must not
    # open a permanent gap in the local inbox.
    # The reservation file is created with CreateNew, so two processes cannot
    # take the same seq.
    param([string]$ArenaRoot, [string]$ProducerId = 'producer', [string]$TaskId = '')
    if ([string]::IsNullOrWhiteSpace($ArenaRoot)) { throw 'reserve: no root' }
    $safeProducer = 'producer'
    if ($ProducerId -match '^[A-Za-z0-9_-]{1,32}$') { $safeProducer = $ProducerId }
    $mutex = $null
    $acquired = $false
    try {
        try {
            $mutex = New-Object System.Threading.Mutex($false, 'Local\ArenaBridge.Seq.v2')
            try {
                $acquired = $mutex.WaitOne(15000)
            }
            catch [System.Threading.AbandonedMutexException] {
                $acquired = $true
            }
        }
        catch {
            $mutex = $null
            $acquired = $false
        }
        if ($null -ne $mutex -and -not $acquired) { throw 'reserve: lock timeout' }
        $inbox = Join-Path $ArenaRoot 'inbox'
        $resDir = Join-Path $ArenaRoot 'reservations'
        foreach ($d in @($inbox, $resDir)) {
            if (-not (Test-Path -LiteralPath $d)) {
                New-Item -ItemType Directory -Path $d -Force | Out-Null
            }
        }
        $max = 0
        $statePath = Join-Path $ArenaRoot 'state.json'
        if (Test-Path -LiteralPath $statePath) {
            $max = [int](Read-State $statePath).last_seq
        }
        else {
            $legacy = $script:LegacyStateFile
            $legacyEnv = [Environment]::GetEnvironmentVariable('ARENA_BRIDGE_LEGACY_STATE_FILE')
            if (-not [string]::IsNullOrWhiteSpace($legacyEnv)) { $legacy = $legacyEnv }
            if (-not [string]::IsNullOrWhiteSpace($legacy)) { $max = Get-SeedLastSeq $legacy }
        }
        foreach ($dir in @($inbox, $resDir)) {
            $files = @(Get-ChildItem -LiteralPath $dir -Filter '*.json' -File -ErrorAction SilentlyContinue)
            foreach ($f in $files) {
                if ($f.BaseName -match '^[1-9][0-9]{0,8}$') {
                    $n = [int]$f.BaseName
                    if ($n -gt $max) { $max = $n }
                }
            }
        }
        for ($i = 1; $i -le 1000; $i++) {
            $seq = $max + $i
            if ($seq -lt 1 -or $seq -gt 999999999) { break }
            $name = "$seq.json"
            $inboxPath = Join-Path $inbox $name
            $resPath = Join-Path $resDir $name
            if ((Test-Path -LiteralPath $inboxPath) -or (Test-Path -LiteralPath $resPath)) {
                continue
            }
            $created = [datetime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
            $taskField = ''
            $reserveId = ('' + $TaskId).ToLowerInvariant()
            if ($reserveId -match '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') {
                $taskField = ',"task_id":"' + $reserveId + '"'
            }
            $json = '{"seq":' + $seq + ',"producer":"' + $safeProducer + '"' + $taskField + ',"created":"' + $created + '"}'
            $fs = $null
            try {
                $fs = New-Object System.IO.FileStream($resPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
                $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
                $fs.Write($bytes, 0, $bytes.Length)
                $fs.Close()
                $fs = $null
                return $seq
            }
            catch {
                if ($null -ne $fs) {
                    try { $fs.Dispose() } catch { }
                    $fs = $null
                }
                continue
            }
        }
        throw 'reserve: no free seq'
    }
    finally {
        if ($acquired -and $null -ne $mutex) {
            try { $mutex.ReleaseMutex() } catch { }
        }
        if ($null -ne $mutex) {
            try { $mutex.Dispose() } catch { }
        }
    }
}

function Complete-TaskReservation {
    param([string]$ArenaRoot, [int]$Seq)
    if ([string]::IsNullOrWhiteSpace($ArenaRoot) -or $Seq -lt 1) { return }
    $path = Join-Path (Join-Path $ArenaRoot 'reservations') ("$Seq.json")
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }
}

function Test-DurableAcceptedSeq {
    # exec_seq already stored for an accepted mailbox task. Expiry of the lease
    # must not reject that slot; recovery still has to write its inbox.
    param($State, [int]$Seq)
    if ($Seq -lt 1 -or $null -eq $State) { return $false }
    if ($null -eq $State.mailbox -or $null -eq $State.mailbox.seen) { return $false }
    foreach ($id in @($State.mailbox.seen.Keys)) {
        $seen = $State.mailbox.seen[$id]
        if ($null -eq $seen) { continue }
        $disp = [string]$seen['disposition']
        if ($disp -ne 'accepted') { continue }
        $seenSeq = 0
        $rawSeq = $seen['seq']
        $seqText = ''
        if ($null -ne $rawSeq) {
            $seqText = [string]$rawSeq
            if ($rawSeq -is [int] -or $rawSeq -is [long] -or $rawSeq -is [double] -or $rawSeq -is [decimal]) {
                $seqText = ([int64]$rawSeq).ToString([System.Globalization.CultureInfo]::InvariantCulture)
            }
        }
        if ($seqText -match '^[0-9]+$') { $seenSeq = [int]$seqText }
        if ($seenSeq -eq $Seq) { return $true }
    }
    return $false
}

function Resolve-ExpiredReservations {
    # Walk only the next missing seq. A live reservation holds the slot.
    # An expired one becomes REJECTED with no execution, then the next task can run.
    # A durable accepted mailbox seq is not abandoned: recovery writes that inbox.
    # A gap with no reservation is left alone so the local inbox still waits.
    param([string]$ArenaRoot, $State, [string]$StatePath)
    if ($null -eq $State -or [string]::IsNullOrWhiteSpace($ArenaRoot)) { return $State }
    $resDir = Join-Path $ArenaRoot 'reservations'
    if (-not (Test-Path -LiteralPath $resDir)) { return $State }
    $lease = Get-SeqLeaseSeconds
    $any = $false
    $guard = 0
    while ($guard -lt 1000) {
        $guard++
        $next = [int]$State.last_seq + 1
        if ($next -lt 1) { break }
        $inbox = Join-Path (Join-Path $ArenaRoot 'inbox') ("$next.json")
        $res = Join-Path $resDir ("$next.json")
        if (Test-Path -LiteralPath $inbox) {
            if (Test-Path -LiteralPath $res) {
                Remove-Item -LiteralPath $res -Force -ErrorAction SilentlyContinue
            }
            break
        }
        if (-not (Test-Path -LiteralPath $res)) { break }
        if (-not (Test-ReservationExpired -Path $res -LeaseSeconds $lease)) { break }
        if (Test-DurableAcceptedSeq $State $next) { break }
        if ($null -eq $State.tasks) { $State.tasks = @{} }
        $State.tasks["$next"] = @{
            action  = ''
            state   = 'REJECTED'
            status  = 'REJECTED'
            reason  = 'reservation-abandoned'
            updated = (Get-Date -Format o)
        }
        $State.last_seq = $next
        Remove-Item -LiteralPath $res -Force -ErrorAction SilentlyContinue
        Write-Host ("REJECTED [" + $next + "]: reservation-abandoned")
        $any = $true
    }
    if ($any -and -not [string]::IsNullOrWhiteSpace($StatePath)) {
        Save-State $StatePath $State
    }
    return $State
}

function Protect-PublicText {
    # Last gate before a body can be stored for a public Issue. Fixed status
    # words stay. Paths, token-shaped strings, and secret assignments do not.
    param([string]$Text)
    if ([string]::IsNullOrEmpty($Text)) { return '' }
    $safe = $Text
    $safe = [regex]::Replace($safe, '[A-Za-z]:\\[^\s\r\n]+', '[redacted]')
    $safe = [regex]::Replace($safe, '\\\\[^\s\r\n]+', '[redacted]')
    $safe = [regex]::Replace($safe, '/(?:home|Users|tmp|var|private|opt|root)/[^\s\r\n]+', '[redacted]')
    $safe = [regex]::Replace($safe, '(?i)\b(?:ghp_|github_pat_|gho_|ghu_|ghs_|ghr_)[A-Za-z0-9_]+', '[redacted]')
    $safe = [regex]::Replace($safe, '(?i)\b(?:sk-|xox[baprs]-|AKIA)[A-Za-z0-9]+', '[redacted]')
    $safe = [regex]::Replace($safe, '(?i)\b(?:password|secret|token|api_key)\s*=\s*\S+', '[redacted]')
    return $safe
}

function Get-PublicResultText {
    # Builds the only result text that may be published. Never returns raw stdout.
    param([string]$Mode, [string]$Text)
    if ([string]::IsNullOrWhiteSpace($Mode) -or $Mode -eq 'none') { return '' }
    if ($null -eq $Text) { $Text = '' }
    if ($Mode -eq 'version') {
        $m = [regex]::Match($Text, '(?m)^git version [0-9][0-9A-Za-z._-]{0,40}\s*$')
        if (-not $m.Success) { return '' }
        return $m.Value.Trim()
    }
    if ($Mode -eq 'status-summary') {
        $branch = 'withheld'
        $bm = [regex]::Match($Text, '(?m)^On branch ([A-Za-z0-9._/-]{1,64})\s*$')
        if ($bm.Success) {
            $candidate = $bm.Groups[1].Value
            if ($candidate -notmatch '\.\.' -and $candidate -notmatch '[\\:]') { $branch = $candidate }
        }
        $tree = 'dirty'
        if ($Text -match 'working tree clean') { $tree = 'clean' }
        return ("branch: " + $branch + "`r`nworking tree: " + $tree)
    }
    if ($Mode -eq 'log-summary') {
        $lines = @()
        $split = $Text -split "`r`n|`n"
        foreach ($line in @($split)) {
            $trim = ([string]$line).Trim()
            if ($trim -notmatch '^[0-9a-f]{7,40} [A-Za-z0-9 ._()/-]{1,80}$') { continue }
            if ($trim -match '[\\:]|/(?:home|Users|tmp|var)/|(?i)password|secret|token|ghp_') { continue }
            $lines += $trim
            if ($lines.Count -ge 10) { break }
        }
        if ($lines.Count -eq 0) { return '' }
        return ($lines -join "`r`n")
    }
    return ''
}

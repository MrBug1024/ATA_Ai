param(
    [ValidateSet("up", "down", "status", "verify", "migrate", "seed", "backend")]
    [string]$Action = "status"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ComposeFile = Join-Path $RepoRoot "deploy\annual-audit\docker-compose.yml"
$EnvFile = Join-Path $RepoRoot "deploy\annual-audit\.env.local"
$SeedFile = Join-Path $RepoRoot "backend\config\annual_audit_auth_seed.json"
$BackendDir = Join-Path $RepoRoot "backend"

function Import-LocalEnvironment {
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        throw "Missing $EnvFile. Copy deploy/annual-audit/.env.example to .env.local first."
    }
    foreach ($line in Get-Content -LiteralPath $EnvFile -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $pair = $trimmed.Split("=", 2)
        if ($pair.Count -ne 2 -or -not $pair[0].Trim()) {
            throw "Invalid environment line in $EnvFile"
        }
        $name = $pair[0].Trim()
        if (
            (-not (Use-LocalMinio) -and $name -like "ANNUAL_MINIO_*") -or
            (Use-ConfiguredMySql -and $name -like "ANNUAL_MYSQL_*") -or
            (Use-ConfiguredRedis -and $name -like "ANNUAL_REDIS_*")
        ) {
            # The local .env.local contains Docker credentials.  Do not let
            # those process variables shadow the configured online values in
            # backend/.env when an online service is configured.
            continue
        }
        [Environment]::SetEnvironmentVariable($name, $pair[1], "Process")
    }
}

function Resolve-DockerCli {
    $fromPath = Get-Command docker -ErrorAction SilentlyContinue
    if ($fromPath) {
        return $fromPath.Source
    }
    $bundled = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"
    if (Test-Path -LiteralPath $bundled) {
        return $bundled
    }
    throw "Docker CLI not found. Start Docker Desktop and verify its installation."
}

function Resolve-ProjectPython {
    if ($env:ANNUAL_PYTHON -and (Test-Path -LiteralPath $env:ANNUAL_PYTHON)) {
        return $env:ANNUAL_PYTHON
    }
    $known = "D:\anaconda3\envs\npaLang_env\python.exe"
    if (Test-Path -LiteralPath $known) {
        return $known
    }
    $fromPath = Get-Command python -ErrorAction SilentlyContinue
    if ($fromPath) {
        return $fromPath.Source
    }
    throw "Project Python not found. Set ANNUAL_PYTHON in the current shell."
}

function Get-BackendSettingValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    # Process environment variables intentionally win over backend/.env, just
    # like pydantic-settings does.  This keeps an explicit shell override
    # useful while still allowing backend/.env to be the normal source.
    $processValue = [Environment]::GetEnvironmentVariable($Name, "Process")
    if (-not [string]::IsNullOrWhiteSpace($processValue)) {
        return $processValue.Trim().Trim('"').Trim("'")
    }

    return Get-BackendEnvFileValue $Name
}

function Get-BackendEnvFileValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $backendEnvFile = Join-Path $BackendDir ".env"
    if (-not (Test-Path -LiteralPath $backendEnvFile)) {
        return ""
    }

    foreach ($line in Get-Content -LiteralPath $backendEnvFile -Encoding UTF8) {
        if ($line -match "^\s*$Name\s*=(.*)$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return ""
}

function Use-LocalMinio {
    # Company MinIO is the default.  The Docker MinIO is only a fallback for
    # a development checkout that has no configured remote endpoint.
    $endpoint = Get-BackendSettingValue "ANNUAL_MINIO_ENDPOINT"
    return [string]::IsNullOrWhiteSpace($endpoint)
}

function Use-ConfiguredMySql {
    $mysqlHost = Get-BackendEnvFileValue "MYSQL_HOST"
    $database = Get-BackendEnvFileValue "MYSQL_DATABASE"
    return (-not [string]::IsNullOrWhiteSpace($mysqlHost)) -and (-not [string]::IsNullOrWhiteSpace($database))
}

function Use-ConfiguredRedis {
    $url = Get-BackendEnvFileValue "REDIS_URL"
    $redisHost = Get-BackendEnvFileValue "REDIS_HOST"
    return (-not [string]::IsNullOrWhiteSpace($url)) -or (-not [string]::IsNullOrWhiteSpace($redisHost))
}

function Use-LocalMySql {
    return -not (Use-ConfiguredMySql)
}

function Use-LocalRedis {
    return -not (Use-ConfiguredRedis)
}

function Set-BackendEnvironment {
    $pgPassword = [Uri]::EscapeDataString($env:ANNUAL_POSTGRES_PASSWORD)
    $mysqlPassword = $env:ANNUAL_MYSQL_PASSWORD
    $redisPassword = [Uri]::EscapeDataString($env:ANNUAL_REDIS_PASSWORD)
    $backendPort = "8080"

    $env:BUSINESS_DOMAIN = "annual_audit"
    $env:APP_PORT = $backendPort
    $env:LANGGRAPH_CHECKPOINTER = "postgres"
    $env:LANGGRAPH_CHECKPOINTER_AUTO_SETUP = "false"
    $env:ANNUAL_POSTGRES_DSN = (
        "postgresql+psycopg://{0}:{1}@127.0.0.1:{2}/{3}" -f
        $env:ANNUAL_POSTGRES_USER,
        $pgPassword,
        $env:ANNUAL_POSTGRES_PORT,
        $env:ANNUAL_POSTGRES_DATABASE
    )
    if (Use-LocalMySql) {
        $env:ANNUAL_MYSQL_HOST = "127.0.0.1"
        $env:ANNUAL_MYSQL_USER = $env:ANNUAL_MYSQL_USER
        $env:ANNUAL_MYSQL_PASSWORD = $mysqlPassword
        $env:ANNUAL_MYSQL_DATABASE = $env:ANNUAL_MYSQL_DATABASE
    }
    else {
        foreach ($name in @(
            "ANNUAL_MYSQL_HOST",
            "ANNUAL_MYSQL_PORT",
            "ANNUAL_MYSQL_USER",
            "ANNUAL_MYSQL_PASSWORD",
            "ANNUAL_MYSQL_DATABASE"
        )) {
            Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        }
    }

    if (Use-LocalRedis) {
        $env:REDIS_URL = "redis://:$redisPassword@127.0.0.1:$($env:ANNUAL_REDIS_PORT)/0"
        $env:ANNUAL_REDIS_NAMESPACE = $env:ANNUAL_REDIS_NAMESPACE
    }
    else {
        foreach ($name in @(
            "REDIS_URL",
            "ANNUAL_REDIS_HOST",
            "ANNUAL_REDIS_PORT",
            "ANNUAL_REDIS_PASSWORD",
            "ANNUAL_REDIS_NAMESPACE"
        )) {
            Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        }
    }
    if (Use-LocalMinio) {
        $env:AI_HUNTER_MINIO_ENABLED = "true"
        $env:AI_HUNTER_MINIO_ENDPOINT = "127.0.0.1:$($env:ANNUAL_MINIO_API_PORT)"
        $env:AI_HUNTER_MINIO_ACCESS_KEY = $env:ANNUAL_MINIO_ACCESS_KEY
        $env:AI_HUNTER_MINIO_SECRET_KEY = $env:ANNUAL_MINIO_SECRET_KEY
        $env:AI_HUNTER_MINIO_BUCKET_RAW = $env:ANNUAL_MINIO_BUCKET_RAW
        $env:AI_HUNTER_MINIO_BUCKET_DERIVED = $env:ANNUAL_MINIO_BUCKET_DERIVED
        $env:AI_HUNTER_MINIO_BUCKET_ARTIFACTS = $env:ANNUAL_MINIO_BUCKET_ARTIFACTS
        $env:AI_HUNTER_MINIO_USE_SSL = "false"
    }
    else {
        # A previous invocation of this script may have left the legacy alias
        # in the current PowerShell process.  Remove it so it cannot override
        # ANNUAL_MINIO_ENDPOINT from backend/.env on the next launch.
        foreach ($name in @(
            "AI_HUNTER_MINIO_ENABLED",
            "AI_HUNTER_MINIO_ENDPOINT",
            "AI_HUNTER_MINIO_ACCESS_KEY",
            "AI_HUNTER_MINIO_SECRET_KEY",
            "AI_HUNTER_MINIO_BUCKET_RAW",
            "AI_HUNTER_MINIO_BUCKET_DERIVED",
            "AI_HUNTER_MINIO_BUCKET_ARTIFACTS",
            "AI_HUNTER_MINIO_USE_SSL"
        )) {
            Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        }
    }
    $env:AUTH_ENABLED = "true"
    $env:AUTH_IDENTITY_MODE = "private"
    $env:AUTH_LOCAL_JWT_SECRET = $env:ANNUAL_AUTH_LOCAL_JWT_SECRET
    $env:USER_CENTER_JWT_SECRET = $env:ANNUAL_AUTH_LOCAL_JWT_SECRET
}

function Invoke-AnnualMigrations {
    Set-BackendEnvironment
    $Python = Resolve-ProjectPython
    Push-Location $BackendDir
    try {
        & $Python -m ai_hunter.annual_audit.storage.migrate
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    finally {
        Pop-Location
    }
}

Import-LocalEnvironment
$composeArgs = @(
    "compose",
    "--env-file", $EnvFile,
    "-f", $ComposeFile
)

switch ($Action) {
    "up" {
        $Docker = Resolve-DockerCli
        $upServices = @("postgres")
        if (Use-LocalMySql) {
            $upServices += "mysql"
        }
        if (Use-LocalRedis) {
            $upServices += "redis"
        }
        if (Use-LocalMinio) {
            $upServices += "minio"
        }
        & $Docker @composeArgs up -d --wait @upServices
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        if (Use-LocalMinio) {
            & $Docker @composeArgs run --rm minio-init
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
        Invoke-AnnualMigrations
    }
    "down" {
        $Docker = Resolve-DockerCli
        & $Docker @composeArgs down
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Write-Output "Containers stopped; named data volumes were preserved."
    }
    "status" {
        $Docker = Resolve-DockerCli
        & $Docker @composeArgs ps
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    "verify" {
        Set-BackendEnvironment
        $Python = Resolve-ProjectPython
        Push-Location $BackendDir
        try {
            & $Python -m ai_hunter.annual_audit.scripts.verify_local_stack
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
        finally {
            Pop-Location
        }
    }
    "migrate" {
        Invoke-AnnualMigrations
    }
    "seed" {
        Invoke-AnnualMigrations
        Set-BackendEnvironment
        $env:INIT_SUPER_ADMIN_PASSWORD = $env:ANNUAL_BOOTSTRAP_SUPERADMIN_PASSWORD
        $Python = Resolve-ProjectPython
        Push-Location $BackendDir
        try {
            & $Python -m ai_hunter.app.scripts.init_local_admin --seed-file $SeedFile
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            & $Python -m ai_hunter.annual_audit.scripts.bootstrap_local_demo
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
        finally {
            Pop-Location
        }
    }
    "backend" {
        Set-BackendEnvironment
        $Python = Resolve-ProjectPython
        Push-Location $BackendDir
        try {
            & $Python -m ai_hunter
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
        finally {
            Pop-Location
        }
    }
}

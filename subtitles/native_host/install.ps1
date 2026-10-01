param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-p]{32}$')]
    [string]$ExtensionId,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.conda\python.exe'
$hostSource = Join-Path $PSScriptRoot 'host.py'
$distDir = Join-Path $PSScriptRoot 'dist'
$buildDir = Join-Path $PSScriptRoot 'build'
$hostExe = Join-Path $distDir 'vat-native-host.exe'
$manifestPath = Join-Path $distDir 'com.video_auto_translate.host.json'
$configPath = Join-Path $distDir 'host-config.json'
$registryPath = 'Software\Google\Chrome\NativeMessagingHosts\com.video_auto_translate.host'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project Python environment is missing: $python"
}

if (-not $SkipBuild) {
    & $python -m PyInstaller --noconfirm --onefile --name vat-native-host `
        --distpath $distDir --workpath $buildDir --specpath $PSScriptRoot $hostSource
    if ($LASTEXITCODE -ne 0) {
        throw 'Native host build failed.'
    }
}
if (-not (Test-Path -LiteralPath $hostExe)) {
    throw "Native host executable is missing: $hostExe"
}

$config = [ordered]@{ project_root = $projectRoot; extension_id = $ExtensionId }
$manifest = [ordered]@{
    name = 'com.video_auto_translate.host'
    description = 'Starts the local Video Auto Translate service'
    path = $hostExe
    type = 'stdio'
    allowed_origins = @("chrome-extension://$ExtensionId/")
}
$config | ConvertTo-Json -Compress | Set-Content -LiteralPath $configPath -Encoding utf8
$manifest | ConvertTo-Json -Compress | Set-Content -LiteralPath $manifestPath -Encoding utf8

$existing = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($registryPath)
if ($null -ne $existing) {
    $existingManifest = $existing.GetValue('')
    $existing.Close()
    if ($existingManifest -and $existingManifest -ne $manifestPath) {
        throw "Native host name is already registered to another manifest: $existingManifest"
    }
}
$key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($registryPath)
try {
    $key.SetValue('', $manifestPath, [Microsoft.Win32.RegistryValueKind]::String)
} finally {
    $key.Close()
}
Write-Output "registered=$registryPath"
Write-Output "manifest=$manifestPath"
Write-Output "host=$hostExe"
Write-Output "extension_id=$ExtensionId"

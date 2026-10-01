$ErrorActionPreference = 'Stop'
$manifestPath = Join-Path $PSScriptRoot 'dist\com.video_auto_translate.host.json'
$registryPath = 'Software\Google\Chrome\NativeMessagingHosts\com.video_auto_translate.host'
$existing = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($registryPath)
if ($null -eq $existing) {
    Write-Output 'Native host is not registered.'
    return
}
$registeredManifest = $existing.GetValue('')
$existing.Close()
if ($registeredManifest -ne $manifestPath) {
    throw "Registration points elsewhere; refusing to remove it: $registeredManifest"
}
[Microsoft.Win32.Registry]::CurrentUser.DeleteSubKey($registryPath, $false)
Write-Output "unregistered=$registryPath"

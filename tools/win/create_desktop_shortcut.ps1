param(
  [Parameter(Mandatory=$true)][string]$Target,
  [Parameter(Mandatory=$true)][string]$Name
)

$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop ($Name + ".lnk")

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Target
$Shortcut.WorkingDirectory = Split-Path $Target -Parent
$Shortcut.IconLocation = $Target
$Shortcut.WindowStyle = 1
$Shortcut.Save()

Write-Host "Created shortcut:" $ShortcutPath

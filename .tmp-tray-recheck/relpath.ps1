. 'C:\work\image-reviwer\tools\tray.ps1' -DefineOnly
"procCWD=" + [Environment]::CurrentDirectory
foreach ($p in '.data', '.\.data', 'C:\work\image-reviwer\.data', 'C:\work\image-reviwer\.data\.', 'C:/work/image-reviwer/.data/', 'C:\work\image-reviwer\tools\..\.data', '\\?\C:\work\image-reviwer\.data', '\\localhost\C$\work\image-reviwer\.data') {
  "{0,-45} real={1}" -f $p, (Test-RealDataDir -Path $p)
}
$short = (New-Object -ComObject Scripting.FileSystemObject).GetFolder('C:\work\image-reviwer\.data').ShortPath
"{0,-45} real={1}" -f $short, (Test-RealDataDir -Path $short)

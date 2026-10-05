Unicode true
RequestExecutionLevel user
ManifestDPIAware true
SetCompressor /SOLID lzma
Name "Rubra ${VERSION}"
OutFile "${OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\Rubra"
InstallDirRegKey HKCU "Software\Rubra" "InstallDir"
Icon "${ICON}"
UninstallIcon "${ICON}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "Rubra"
VIAddVersionKey "FileDescription" "Rubra installer"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "Rubra contributors"
!include "MUI2.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
!define MUI_WELCOMEPAGE_TEXT "Rubra installs for your Windows account without administrator access. Python is included. Roblox Studio and Microsoft WebView2 are platform dependencies.$\r$\n$\r$\nClose Rubra before updating. Existing data and downloaded tools are preserved."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${PACKAGE}/LICENSE"
!define MUI_DIRECTORYPAGE_TEXT_TOP "Choose where Rubra will be installed. Select an empty writable folder, or the existing Rubra installation to update it."
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\Rubra.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Open Rubra"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "Rubra requires 64-bit Windows."
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_OK|MB_ICONSTOP "Rubra requires Windows 10 or later."
    Abort
  ${EndIf}
FunctionEnd

Function .onVerifyInstDir
  ReadINIStr $0 "$INSTDIR\rubra-install.ini" "Application" "Product"
  StrCmp $0 "Rubra" valid
  IfFileExists "$INSTDIR\*" 0 valid
  MessageBox MB_OK|MB_ICONEXCLAMATION "Choose an empty folder or the existing Rubra installation."
  Abort
  valid:
FunctionEnd

Section "Rubra"
  SetShellVarContext current
  ReadINIStr $0 "$INSTDIR\rubra-install.ini" "Application" "Product"
  StrCmp $0 "Rubra" extract
  IfFileExists "$INSTDIR\*" 0 extract
  MessageBox MB_OK|MB_ICONSTOP "Choose an empty folder or the existing installed Rubra folder."
  Abort
  extract:
  CreateDirectory "$INSTDIR"
  ClearErrors
  FileOpen $1 "$INSTDIR\.rubra-write-check" w
  IfErrors unwritable
  FileClose $1
  Delete "$INSTDIR\.rubra-write-check"

  ; Application code and bundled Python are immutable release payloads.
  ; Replace them completely on update so removed/renamed files from an older
  ; release cannot survive and shadow the new code. User data, downloaded
  ; tools, models and caches elsewhere under runtime are intentionally kept.
  ; Rubra.exe remains alive while the Python desktop process is running.
  ; Probe/remove it first so an open installation aborts before any immutable
  ; payload is deleted.
  ClearErrors
  Delete "$INSTDIR\Rubra.exe"
  IfErrors close_required
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\runtime\python"
  IfErrors close_required

  SetOutPath "$INSTDIR"
  ClearErrors
  File /r "${PACKAGE}/*"
  IfErrors install_failed
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteINIStr "$INSTDIR\rubra-install.ini" "Application" "Product" "Rubra"
  WriteRegStr HKCU "Software\Rubra" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Rubra" "DisplayName" "Rubra"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Rubra" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Rubra" "DisplayIcon" "$INSTDIR\Rubra.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Rubra" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Rubra" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Rubra" "NoRepair" 1
  CreateDirectory "$SMPROGRAMS\Rubra"
  CreateShortcut "$SMPROGRAMS\Rubra\Rubra.lnk" "$INSTDIR\Rubra.exe" "" "$INSTDIR\Rubra.exe"
  CreateShortcut "$DESKTOP\Rubra.lnk" "$INSTDIR\Rubra.exe" "" "$INSTDIR\Rubra.exe"
  Goto done
  close_required:
  MessageBox MB_OK|MB_ICONSTOP "Rubra is still using application files. Quit Rubra from the notification area, then run the installer again."
  Abort
  install_failed:
  MessageBox MB_OK|MB_ICONSTOP "Rubra could not update all application files. Close Rubra completely and run the installer again."
  Abort
  unwritable:
  MessageBox MB_OK|MB_ICONSTOP "Rubra cannot write to this folder. Choose a folder that your Windows account can access."
  Abort
  done:
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  Delete "$DESKTOP\Rubra.lnk"
  Delete "$SMPROGRAMS\Rubra\Rubra.lnk"
  RMDir "$SMPROGRAMS\Rubra"
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\data"
  Delete "$INSTDIR\Rubra.exe"
  Delete "$INSTDIR\Uninstall.exe"
  Delete "$INSTDIR\rubra-install.ini"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\NOTICE.md"
  Delete "$INSTDIR\README.md"
  Delete "$INSTDIR\RUBRA.md"
  Delete "$INSTDIR\NSIS-LICENSE.txt"
  Delete "$INSTDIR\START_HERE.txt"
  Delete "$INSTDIR\RELEASE_NOTES.md"
  Delete "$INSTDIR\release.json"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Rubra"
  DeleteRegKey HKCU "Software\Rubra"
SectionEnd

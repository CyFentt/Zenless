Unicode true
RequestExecutionLevel user
SilentInstall silent
AutoCloseWindow true
ManifestDPIAware true
Name "Rubra"
Icon "${ICON}"
OutFile "${OUTPUT}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "Rubra"
VIAddVersionKey "FileDescription" "Rubra portable launcher"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "Rubra contributors"
!include "FileFunc.nsh"
!include "x64.nsh"
!include "WinVer.nsh"

Section
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "Rubra requires 64-bit Windows."
    SetErrorLevel 1
    Quit
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_OK|MB_ICONSTOP "Rubra requires Windows 10 or later."
    SetErrorLevel 1
    Quit
  ${EndIf}
  IfFileExists "$EXEDIR\runtime\python\pythonw.exe" 0 incomplete
  IfFileExists "$EXEDIR\app\main.py" 0 incomplete
  SetOutPath "$EXEDIR"
  System::Call 'kernel32::SetEnvironmentVariableW(w "RUBRA_HOME", w "$EXEDIR") i.r0'
  StrCmp $0 0 failed
  ${GetParameters} $0
  ClearErrors
  ExecWait '"$EXEDIR\runtime\python\pythonw.exe" -s "$EXEDIR\app\main.py" $0' $1
  IfErrors failed
  StrCmp $1 0 complete
  MessageBox MB_OK|MB_ICONSTOP "Rubra exited with an error. Review data\startup-error.log and data\logs. If no log exists, extract the package into a writable folder."
  complete:
  SetErrorLevel $1
  Quit
  incomplete:
    MessageBox MB_OK|MB_ICONSTOP "Extract the entire Rubra folder before opening Rubra.exe."
    SetErrorLevel 1
    Quit
  failed:
    MessageBox MB_OK|MB_ICONSTOP "Rubra could not start its bundled Python runtime. Check folder permissions and extract the complete package."
    SetErrorLevel 1
SectionEnd

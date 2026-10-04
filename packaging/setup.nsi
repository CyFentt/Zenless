Unicode true
RequestExecutionLevel user
ManifestDPIAware true
SetCompressor /SOLID lzma
Name "Rubra ${VERSION}"
OutFile "${OUTPUT}"
InstallDir "$PROFILE\Rubra"
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "Rubra"
VIAddVersionKey "FileDescription" "Rubra portable setup"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "Rubra contributors"
!include "MUI2.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
!define MUI_WELCOMEPAGE_TEXT "Rubra will be extracted into one folder. Python is included. Rubra downloads its tools on first launch. Roblox Studio and Microsoft WebView2 are platform dependencies.$\r$\n$\r$\nChoose a new writable folder. Remove that folder to remove Rubra."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${PACKAGE}/LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\Rubra.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Open Rubra"
!insertmacro MUI_PAGE_FINISH
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
  IfFileExists "$INSTDIR\*" 0 valid
  Abort
  valid:
FunctionEnd

Section "Rubra"
  IfFileExists "$INSTDIR\*" 0 extract
  MessageBox MB_OK|MB_ICONSTOP "Choose an empty folder. Existing Rubra data will not be overwritten."
  Abort
  extract:
  SetOutPath "$INSTDIR"
  File /r "${PACKAGE}/*"
SectionEnd

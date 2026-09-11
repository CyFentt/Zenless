Unicode True
!include "FileFunc.nsh"
!include "LogicLib.nsh"
!include "nsDialogs.nsh"
RequestExecutionLevel user
SetCompressor /SOLID lzma
Name "Zenless"
OutFile "..\dist\ZenlessSetup.exe"
InstallDir "$LOCALAPPDATA\Programs\Zenless"
!if /FileExists "..\assets\zenless.ico"
Icon "..\assets\zenless.ico"
UninstallIcon "..\assets\zenless.ico"
!endif
VIProductVersion "2.1.0.0"
VIAddVersionKey "ProductName" "Zenless"
VIAddVersionKey "FileDescription" "Zenless Setup"
VIAddVersionKey "FileVersion" "2.1.0"
VIAddVersionKey "ProductVersion" "2.1.0"
VIAddVersionKey "LegalCopyright" "Zenless"
Page instfiles
UninstPage custom un.ModePage un.ModePageLeave
UninstPage instfiles
Var KeepData
Var KeepDataCheckbox
Var WaitPid

Function .onInit
  SetShellVarContext current
  StrCpy $INSTDIR "$LOCALAPPDATA\Programs\Zenless"
FunctionEnd

Function un.onInit
  SetShellVarContext current
  StrCpy $INSTDIR "$LOCALAPPDATA\Programs\Zenless"
  StrCpy $KeepData 1
  StrCpy $WaitPid 0
  ${GetOptions} $CMDLINE "/REMOVEDATA" $0
  IfErrors +2
  StrCpy $KeepData 0
  ${GetOptions} $CMDLINE "/KEEPDATA" $0
  IfErrors +2
  StrCpy $KeepData 1
  ${GetOptions} $CMDLINE "/WAITPID=" $0
  IfErrors +2
  StrCpy $WaitPid $0
FunctionEnd

Function un.ModePage
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ${NSD_CreateLabel} 0 0 100% 24u "Choose whether Zenless settings and provider sessions should be kept."
  Pop $0
  ${NSD_CreateCheckbox} 0 32u 100% 12u "Keep settings and sessions"
  Pop $KeepDataCheckbox
  ${NSD_Check} $KeepDataCheckbox
  nsDialogs::Show
FunctionEnd

Function un.ModePageLeave
  ${NSD_GetState} $KeepDataCheckbox $0
  StrCmp $0 ${BST_CHECKED} 0 +2
  StrCpy $KeepData 1
  StrCmp $0 ${BST_CHECKED} +2 0
  StrCpy $KeepData 0
FunctionEnd

Function un.WaitForZenless
  StrCmp $WaitPid 0 done
  System::Call 'kernel32::OpenProcess(i 0x00100000, i 0, i $WaitPid) p.r0'
  StrCmp $0 0 done
  System::Call 'kernel32::WaitForSingleObject(p r0, i 60000) i.r1'
  System::Call 'kernel32::CloseHandle(p r0)'
  IntCmp $1 258 timeout done done
timeout:
  SetErrorLevel 2
  Quit
done:
FunctionEnd

Function un.Fail
  IfSilent +2
  MessageBox MB_ICONSTOP|MB_OK "Zenless could not be completely removed. Close Zenless and try again."
  SetErrorLevel 2
  Quit
FunctionEnd

Section "Zenless" Main
  SetShellVarContext current
  StrCpy $INSTDIR "$LOCALAPPDATA\Programs\Zenless"
  SetOutPath "$INSTDIR"
  File "..\dist\Zenless.exe"
  WriteUninstaller "$INSTDIR\Uninstall Zenless.exe"
  CreateDirectory "$SMPROGRAMS\Zenless"
  CreateShortcut "$SMPROGRAMS\Zenless\Zenless.lnk" "$INSTDIR\Zenless.exe"
  CreateShortcut "$SMPROGRAMS\Zenless\Uninstall Zenless.lnk" "$INSTDIR\Uninstall Zenless.exe"
  CreateShortcut "$DESKTOP\Zenless.lnk" "$INSTDIR\Zenless.exe"
  WriteRegStr HKCU "Software\Zenless" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Zenless" "DisplayName" "Zenless"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Zenless" "DisplayIcon" "$INSTDIR\Zenless.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Zenless" "DisplayVersion" "2.1.0"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Zenless" "Publisher" "Zenless"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Zenless" "UninstallString" "$\"$INSTDIR\Uninstall Zenless.exe$\""
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Zenless" "QuietUninstallString" "$\"$INSTDIR\Uninstall Zenless.exe$\" /S /KEEPDATA"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Zenless" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Zenless" "NoRepair" 1
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  StrCpy $INSTDIR "$LOCALAPPDATA\Programs\Zenless"
  Call un.WaitForZenless
  SetOutPath "$TEMP"
  StrCmp $KeepData 1 data_done
  ClearErrors
  RMDir /r "$LOCALAPPDATA\Zenless"
  IfErrors 0 data_done
  Call un.Fail
data_done:
  ClearErrors
  Delete "$INSTDIR\Zenless.exe"
  IfErrors 0 +2
  Call un.Fail
  ClearErrors
  Delete "$INSTDIR\Uninstall Zenless.exe"
  IfErrors 0 +2
  Call un.Fail
  ClearErrors
  RMDir "$INSTDIR"
  IfErrors 0 +2
  Call un.Fail
  Delete "$DESKTOP\Zenless.lnk"
  Delete "$SMPROGRAMS\Zenless\Zenless.lnk"
  Delete "$SMPROGRAMS\Zenless\Uninstall Zenless.lnk"
  RMDir "$SMPROGRAMS\Zenless"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Zenless"
  DeleteRegKey HKCU "Software\Zenless"
SectionEnd

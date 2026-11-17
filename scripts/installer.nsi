Unicode true
; AutoClicker 安装包模板（NSIS 3.x）
; 由 scripts/publish_package.ps1 调用，版本号/产物路径全部通过 /D 传入，模板本身不写死版本。
;
; 必传定义：
;   APP_VERSION  产品版本，如 2.0.2
;   APP_BUILD    构建版本，如 20261117-002
;   APP_ARCH     架构标识，如 win64
;   SRC_EXE      待打包的 AutoClicker.exe 绝对路径
;   OUT_FILE     输出安装包绝对路径
; 可选定义：
;   APP_ICON     安装包/卸载项图标（.ico 绝对路径）
;   DOC_README   README 绝对路径
;   DOC_LICENSE  LICENSE 绝对路径

!include "MUI2.nsh"
!include "FileFunc.nsh"

!ifndef APP_VERSION
  !define APP_VERSION "0.0.0"
!endif
!ifndef APP_BUILD
  !define APP_BUILD "unknown"
!endif
!ifndef APP_ARCH
  !define APP_ARCH "win64"
!endif
!ifndef SRC_EXE
  !error "SRC_EXE 未定义：请通过 /DSRC_EXE=... 传入 AutoClicker.exe 路径"
!endif
!ifndef OUT_FILE
  !define OUT_FILE "AutoClicker-Setup.exe"
!endif

Name "AutoClicker ${APP_VERSION}"
OutFile "${OUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\AutoClicker"
InstallDirRegKey HKCU "Software\AutoClicker" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "AutoClicker ${APP_VERSION} (${APP_BUILD})"

VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey "ProductName" "AutoClicker"
VIAddVersionKey "FileDescription" "AutoClicker 安装程序"
VIAddVersionKey "FileVersion" "${APP_VERSION} (${APP_BUILD})"
VIAddVersionKey "ProductVersion" "${APP_VERSION} (${APP_BUILD})"
VIAddVersionKey "LegalCopyright" "AutoClicker"

!ifdef APP_ICON
  !define MUI_ICON "${APP_ICON}"
  !define MUI_UNICON "${APP_ICON}"
!endif

!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\AutoClicker.exe"
!define MUI_FINISHPAGE_RUN_TEXT "立即启动 AutoClicker"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

Section "AutoClicker 主程序" SEC_MAIN
  SetOutPath "$INSTDIR"
  File "${SRC_EXE}"
!ifdef DOC_README
  File "${DOC_README}"
!endif
!ifdef DOC_LICENSE
  File "${DOC_LICENSE}"
!endif
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  CreateDirectory "$SMPROGRAMS\AutoClicker"
  CreateShortcut "$SMPROGRAMS\AutoClicker\AutoClicker.lnk" "$INSTDIR\AutoClicker.exe"
  CreateShortcut "$SMPROGRAMS\AutoClicker\卸载 AutoClicker.lnk" "$INSTDIR\Uninstall.exe"

  WriteRegStr HKCU "Software\AutoClicker" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\AutoClicker" "Version" "${APP_VERSION}"
  WriteRegStr HKCU "Software\AutoClicker" "Build" "${APP_BUILD}"

  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoClicker" "DisplayName" "AutoClicker ${APP_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoClicker" "DisplayVersion" "${APP_VERSION} (${APP_BUILD})"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoClicker" "DisplayIcon" "$INSTDIR\AutoClicker.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoClicker" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoClicker" "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoClicker" "Publisher" "AutoClicker"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoClicker" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoClicker" "NoRepair" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoClicker" "EstimatedSize" "$0"
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\AutoClicker.exe"
  Delete "$INSTDIR\README.md"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"

  Delete "$SMPROGRAMS\AutoClicker\AutoClicker.lnk"
  Delete "$SMPROGRAMS\AutoClicker\卸载 AutoClicker.lnk"
  RMDir "$SMPROGRAMS\AutoClicker"

  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoClicker"
  DeleteRegKey HKCU "Software\AutoClicker"
SectionEnd

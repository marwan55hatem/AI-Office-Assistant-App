; Inno Setup 6 script for the Desktop AI Office Assistant.
; Build after PyInstaller:  iscc packaging\installer.iss
; Input : dist\OfficeAssistant\      (PyInstaller onedir output, models included)
; Output: dist\installer\OfficeAssistant-Setup.exe + OfficeAssistant-Setup-N.bin

#define MyAppName      "Office Assistant"
#define MyAppVersion   "1.0.0"
#define MyAppPublisher "TM471B - Arab Open University"
#define MyAppExe       "OfficeAssistant.exe"
#define MyAdminExe     "OfficeAssistant-Admin.exe"
; Both can be overridden on the command line: iscc /DSourceDir=... /DOutDir=... installer.iss
#ifndef SourceDir
  #define SourceDir    "..\dist\OfficeAssistant"
#endif
#ifndef OutDir
  #define OutDir       "..\dist\installer"
#endif

[Setup]
AppId={{6B1C3E2A-4F7D-4C1B-9A8E-0F3D5A7C2B91}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir={#OutDir}
OutputBaseFilename=OfficeAssistant-Setup
SetupIconFile=..\assets\icons\app.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2/ultra64
SolidCompression=no
LZMAUseSeparateProcess=yes
; The payload is larger than 4 GB: split into Setup.exe + .bin parts.
DiskSpanning=yes
DiskSliceSize=2000000000
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=admin
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\USER_GUIDE.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\INSTALL.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\TROUBLESHOOTING.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\{#MyAppName} Admin"; Filename: "{app}\{#MyAdminExe}"
Name: "{group}\User guide"; Filename: "{app}\docs\USER_GUIDE.md"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
// Ask on uninstall whether to delete the user's data (database + logs).
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\OfficeAssistant');
    if DirExists(DataDir) then
      if MsgBox('Also delete your Office Assistant data (accounts, sessions, tasks, chats)?' + #13#10 +
                DataDir + #13#10#13#10 + 'Choose No to keep it for a later reinstall.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;

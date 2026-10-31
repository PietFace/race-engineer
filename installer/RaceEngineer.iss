; Installer voor AI Race Engineer (Inno Setup 6)
; Wordt automatisch gebouwd door GitHub (zie .github/workflows/release.yml).
; Zelf bouwen: ISCC.exe /DAppVersion=2.0.0 installer\RaceEngineer.iss

#ifndef AppVersion
  #define AppVersion "2.0.0"
#endif
#define AppName "AI Race Engineer"
#define AppExe "RaceEngineer.exe"

[Setup]
AppId={{6F1C2B7A-5E3D-4C1B-9A8E-2D4F7B9C1E35}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=AI Race Engineer
DefaultDirName={localappdata}\Programs\RaceEngineer
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; installeren zonder administrator-rechten (alleen voor deze gebruiker)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\Output
OutputBaseFilename=RaceEngineer-Setup
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
WizardStyle=modern
WizardImageFile=wizard_big.bmp
WizardSmallImageFile=wizard_small.bmp
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "dutch"; MessagesFile: "compiler:Languages\Dutch.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\RaceEngineer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; Instellingen en referentierondes staan in %APPDATA%\RaceEngineer en blijven bij updates gewoon bewaard.

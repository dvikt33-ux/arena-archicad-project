; ACCOLLAB Setup v0.2.0 (Inno Setup 6). Sborka: iscc setup.iss (posle PyInstaller).
; Vse stroki - translitom (bez problem kodirovok).
#define MyAppName "ACCOLLAB"
#define MyAppVersion "0.2.0"
#define MyAppExeName "accollab.exe"

[Setup]
AppId={{1a47b538-aafc-499e-af7c-b29191c3f212}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=ACCOLLAB-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayName={#MyAppName} {#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "tapir"; Description: "Ustanovit Tapir 1.5.9 v Archicad 29 (mozhet sprosit prava administratora)"; Flags: checkedonce

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "TapirAddOn_AC29_Win.apx"; DestDir: "{app}"; Flags: ignoreversion
Source: "tapir-LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "USTANOVKA.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\Proverka (once)"; Filename: "{cmd}"; Parameters: "/k ""{app}\{#MyAppExeName}"" --config ""{userappdata}\ACCOLLAB\accollab.json"" once"
Name: "{group}\Status"; Filename: "{cmd}"; Parameters: "/k ""{app}\{#MyAppExeName}"" --config ""{userappdata}\ACCOLLAB\accollab.json"" status"
Name: "{group}\Instruktsiya"; Filename: "notepad.exe"; Parameters: """{app}\USTANOVKA.txt"""

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--config ""{userappdata}\ACCOLLAB\accollab.json"" init --author ""{username}"""; Flags: runhidden; StatusMsg: "Sozdaju config..."

[Code]
const
  AC29Dir = 'C:\Program Files\GRAPHISOFT\ARCHICAD 29';
  ApxName = 'TapirAddOn_AC29_Win.apx';

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not DirExists(AC29Dir) then
    MsgBox('Archicad 29 v standartnoj papke ne najden.'#13#10
      + 'Ustanovka prodolzhitsja, no proverte, gde stoit vash Archicad 29.',
      mbInformation, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  FromF, ToF: String;
begin
  if CurStep = ssPostInstall then
  begin
    if WizardIsTaskSelected('tapir') then
    begin
      FromF := ExpandConstant('{app}\' + ApxName);
      ToF := AC29Dir + '\Add-Ons\' + ApxName;
      if DirExists(AC29Dir + '\Add-Ons') and FileCopy(FromF, ToF, False) then
        MsgBox('Tapir ustanovlen v Add-Ons. Perezapustite Archicad 29.',
          mbInformation, MB_OK)
      else
        MsgBox('Ne poluchilos skopirovat Tapir v Add-Ons (net prav ili drugoj put?).'#13#10
          + 'Fajl lezhit zdes: ' + FromF + #13#10
          + 'Podkljuchite vruchnuju: Archicad - Parametry - Dispetcher nadstroek - Add - vybrat APX.',
          mbInformation, MB_OK);
    end;
  end;
end;

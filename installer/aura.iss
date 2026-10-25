; Inno Setup script for the Aura installer. Build dist\Aura with PyInstaller first, then
;     iscc installer\aura.iss
; Installs for the current user only, so it never asks for admin rights.

#define AppVersion GetEnv("AURA_VERSION")
#if AppVersion == ""
  #define AppVersion "1.1.0"
#endif

[Setup]
AppId={{6F2B1C7A-3D4E-4B8F-9A61-2C5D7E8F9A10}
AppName=Aura
AppVersion={#AppVersion}
AppPublisher=Matin Nikoomanzar
AppPublisherURL=https://github.com/MatinNikoo/aura-widgets
DefaultDirName={localappdata}\Programs\Aura
DefaultGroupName=Aura
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=AuraSetup-{#AppVersion}
SetupIconFile=aura.ico
UninstallDisplayIcon={app}\Aura.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
CloseApplications=force

[Tasks]
Name: "music"; Description: "Now playing card"; GroupDescription: "Open when my PC starts:"
Name: "clock"; Description: "Clock"; GroupDescription: "Open when my PC starts:"; Flags: unchecked
Name: "gif"; Description: "GIF box"; GroupDescription: "Open when my PC starts:"; Flags: unchecked

[Files]
Source: "..\dist\Aura\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Aura now playing"; Filename: "{app}\Aura.exe"; Parameters: "aura_widget"
Name: "{group}\Aura clock"; Filename: "{app}\Aura.exe"; Parameters: "aura_clock"
Name: "{group}\Aura GIF box"; Filename: "{app}\Aura.exe"; Parameters: "aura_gif"
Name: "{group}\Aura tall GIF box"; Filename: "{app}\Aura.exe"; Parameters: "aura_gif_tall"
Name: "{group}\Aura settings"; Filename: "{app}\Aura.exe"; Parameters: "settings"
Name: "{group}\Uninstall Aura"; Filename: "{uninstallexe}"

; the same Run values the widgets write themselves, so their "Open when my PC starts" menus stay in sync
[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AuraWidget"; ValueData: """{app}\Aura.exe"" aura_widget"; Tasks: music; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AuraClockWidget"; ValueData: """{app}\Aura.exe"" aura_clock"; Tasks: clock; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AuraGifWidget"; ValueData: """{app}\Aura.exe"" aura_gif"; Tasks: gif; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Aura.exe"; Parameters: "aura_widget"; Description: "Open the now playing card"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im Aura.exe"; Flags: runhidden; RunOnceId: "CloseAura"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Names: TArrayOfString;
  I: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    { widgets the user turned on from their own menus, including GIF box copies }
    if RegGetValueNames(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', Names) then
      for I := 0 to GetArrayLength(Names) - 1 do
        if (Names[I] = 'AuraWidget') or (Names[I] = 'AuraClockWidget') or (Names[I] = 'AuraGifWidget') or (Pos('Aura_', Names[I]) = 1) then
          RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', Names[I]);
    if SuppressibleMsgBox('Also delete your Aura settings, logs and saved GIFs?', mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
    begin
      DelTree(ExpandConstant('{userappdata}\Aura'), True, True, True);
      RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Aura');
    end;
  end;
end;

param(
    [string]$ToolchainRoot = (Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'android-toolchain'),
    [string]$PythonExecutable = (Join-Path (Split-Path $PSScriptRoot -Parent) '.venv/Scripts/python.exe')
)
$ErrorActionPreference='Stop'
$ToolchainRoot=[IO.Path]::GetFullPath($ToolchainRoot)
$env:JAVA_HOME=Join-Path $ToolchainRoot 'jdk'
$env:ANDROID_HOME=Join-Path $ToolchainRoot 'sdk'
$env:ANDROID_USER_HOME=Join-Path $ToolchainRoot 'android-user'
$env:MAVEN_OPTS="-Duser.home=$ToolchainRoot/user-home -Dfile.encoding=UTF-8"
$env:TEMP=Join-Path $ToolchainRoot 'temp'
$env:TMP=$env:TEMP
$env:JAVA_TOOL_OPTIONS="-Duser.home=$ToolchainRoot/user-home"
New-Item -ItemType Directory -Force -Path $env:TEMP,$env:ANDROID_USER_HOME | Out-Null
$maven=Join-Path $ToolchainRoot 'apache-maven-3.10.0/bin/mvn.cmd'
if (-not (Test-Path -LiteralPath $maven)) { throw '请先准备 JDK 17、Maven 3.10 和 Android SDK 35，参见 docs/android.md。' }
if (-not (Test-Path -LiteralPath $PythonExecutable)) { throw '找不到 Python；请通过 -PythonExecutable 指定 Python 3.10+ 的路径。' }
{
    $signingDir=Join-Path $ToolchainRoot 'signing'
    New-Item -ItemType Directory -Force -Path $signingDir | Out-Null
    $signingConfig=Join-Path $signingDir 'release.json'
    if (-not (Test-Path -LiteralPath $signingConfig)) {
        $bytes=New-Object byte[] 36
        [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
        $password=[Convert]::ToBase64String($bytes)
        $keyPath=Join-Path $signingDir 'auto-chaoxing-release.jks'
        if (Test-Path -LiteralPath $keyPath) { throw '已有签名密钥，但缺少配置文件；请恢复签名配置，避免覆盖现有密钥。' }
        $env:AUTO_CHAOXING_ANDROID_STORE_PASSWORD=$password
        $env:AUTO_CHAOXING_ANDROID_KEY_PASSWORD=$password
        & (Join-Path $env:JAVA_HOME 'bin/keytool.exe') -genkeypair -keystore $keyPath -storetype PKCS12 -alias auto-chaoxing -keyalg RSA -keysize 3072 -validity 10000 -dname 'CN=Auto Chaoxing Tool' -storepass:env AUTO_CHAOXING_ANDROID_STORE_PASSWORD -keypass:env AUTO_CHAOXING_ANDROID_KEY_PASSWORD
        if ($LASTEXITCODE -ne 0) { throw '创建本地签名密钥失败' }
        @{store=$keyPath;password=$password} | ConvertTo-Json | Set-Content -LiteralPath $signingConfig -Encoding utf8
        $who=[Security.Principal.WindowsIdentity]::GetCurrent().Name
        & icacls.exe $signingDir /inheritance:r /grant:r "${who}:(OI)(CI)F" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw '设置签名目录权限失败' }
    }
    $private=Get-Content -LiteralPath $signingConfig -Raw | ConvertFrom-Json
    $env:AUTO_CHAOXING_ANDROID_KEYSTORE=$private.store
    $env:AUTO_CHAOXING_ANDROID_STORE_PASSWORD=$private.password
    $env:AUTO_CHAOXING_ANDROID_KEY_PASSWORD=$private.password
}.Invoke()
try {
    & $maven -B -f (Join-Path $PSScriptRoot 'pom.xml') "-Dmaven.repo.local=$ToolchainRoot/maven-repository" "-Dpython.executable=$PythonExecutable" clean package
    if ($LASTEXITCODE -ne 0) { throw 'Maven Android 构建未通过' }
    $apk=Join-Path $PSScriptRoot 'target/auto-chaoxing-tool-0.11.0-release.apk'
    if (-not (Test-Path -LiteralPath $apk)) { throw '没有找到 APK 构建产物' }
    $artifacts=Join-Path (Split-Path $PSScriptRoot -Parent) 'dist'
    New-Item -ItemType Directory -Force -Path $artifacts | Out-Null
    $output=Join-Path $artifacts 'auto-chaoxing-tool-0.11.0-release.apk'
    Copy-Item -LiteralPath $apk -Destination $output
    Write-Output "APK: $output"
    Get-FileHash -LiteralPath $output -Algorithm SHA256
} finally {
    Remove-Item Env:AUTO_CHAOXING_ANDROID_KEYSTORE -ErrorAction SilentlyContinue
    Remove-Item Env:AUTO_CHAOXING_ANDROID_STORE_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:AUTO_CHAOXING_ANDROID_KEY_PASSWORD -ErrorAction SilentlyContinue
}

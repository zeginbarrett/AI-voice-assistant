param(
    [Parameter(Mandatory=$true)][string]$TextPath,
    [Parameter(Mandatory=$true)][string]$OutPath,
    [string]$VoiceName = ""
)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Speech
$spoken = [System.IO.File]::ReadAllText($TextPath, [System.Text.Encoding]::UTF8)
$speech = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    if ($VoiceName) { try { $speech.SelectVoice($VoiceName) } catch { $speech.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::Female) } }
    else { try { $speech.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::Female) } catch { } }
    $fmt = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(
        16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono)
    $speech.SetOutputToWaveFile($OutPath, $fmt)
    $esc = [System.Security.SecurityElement]::Escape($spoken)
    # Fallback SAPI voice. Set SAM to Piper for natural neural female speech.
    # Natural gamer-girl TTS will be a separate voice-engine upgrade.
    $ssml = "<speak version='1.0' xml:lang='en-US'><prosody pitch='+5%' rate='+3%'>$esc</prosody></speak>"
    try { $speech.SpeakSsml($ssml) }
    catch { $speech.Speak($spoken) }
} finally {
    $speech.Dispose()
}

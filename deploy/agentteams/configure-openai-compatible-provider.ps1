[CmdletBinding()]
# Run after deploy.ps1 because applying AgentTeams resources restores hiclaw-gateway.
param(
    [Parameter(Mandatory)]
    [string]$ProfilePath,
    [ValidateNotNullOrEmpty()]
    [ValidatePattern("^hiclaw-(manager|worker-[A-Za-z0-9._-]+)$")]
    [string[]]$Containers = @(
        "hiclaw-manager",
        "hiclaw-worker-agentloom-investigator",
        "hiclaw-worker-agentloom-implementer",
        "hiclaw-worker-agentloom-verifier"
    ),
    [switch]$RunConnectionTest,
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
$SchemaVersion = "agentloom.provider-profile/v1alpha1"
$AllowedProfileFields = @(
    "schemaVersion",
    "providerId",
    "displayName",
    "baseUrl",
    "modelId",
    "apiKeyEnvironmentVariable",
    "generate"
)
$RequiredProfileFields = @(
    "schemaVersion",
    "providerId",
    "displayName",
    "baseUrl",
    "modelId",
    "apiKeyEnvironmentVariable"
)
$AllowedGenerateFields = @(
    "temperature",
    "maxTokens",
    "topP",
    "reasoningEffort"
)

function Test-PublicEndpointHost {
    param([Parameter(Mandatory)][string]$HostName)

    $normalized = $HostName.TrimEnd(".").ToLowerInvariant()
    if ($normalized -eq "localhost" -or $normalized.EndsWith(".localhost")) {
        return $false
    }

    $address = $null
    if (-not [Net.IPAddress]::TryParse($normalized, [ref]$address)) {
        return $true
    }
    if ([Net.IPAddress]::IsLoopback($address)) {
        return $false
    }
    if ($address.IsIPv4MappedToIPv6) {
        $address = $address.MapToIPv4()
    }
    if ($address.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork) {
        $bytes = $address.GetAddressBytes()
        return -not (
            $bytes[0] -eq 0 -or
            $bytes[0] -eq 10 -or
            $bytes[0] -eq 127 -or
            ($bytes[0] -eq 169 -and $bytes[1] -eq 254) -or
            ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or
            ($bytes[0] -eq 192 -and $bytes[1] -eq 168) -or
            $bytes[0] -ge 224
        )
    }

    $ipv6Bytes = $address.GetAddressBytes()
    return -not (
        $address.IsIPv6LinkLocal -or
        $address.IsIPv6SiteLocal -or
        $address.IsIPv6Multicast -or
        (($ipv6Bytes[0] -band 0xFE) -eq 0xFC)
    )
}

function Test-JsonNumber {
    param([object]$Value)

    return $Value -is [byte] -or
        $Value -is [short] -or
        $Value -is [int] -or
        $Value -is [long] -or
        $Value -is [single] -or
        $Value -is [double] -or
        $Value -is [decimal]
}

function Read-ProviderProfile {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Provider Profile file is unavailable"
    }
    $profileFile = Get-Item -LiteralPath $Path
    if ($profileFile.Length -gt 65536) {
        throw "Provider Profile exceeds 65536 bytes"
    }
    try {
        $profile = Get-Content -Raw -LiteralPath $profileFile.FullName |
            ConvertFrom-Json -AsHashtable -Depth 10
    }
    catch {
        throw "Provider Profile is not valid JSON"
    }
    if ($profile -isnot [Collections.IDictionary]) {
        throw "Provider Profile must be a JSON object"
    }
    foreach ($field in $profile.Keys) {
        if ($field -cnotin $AllowedProfileFields) {
            throw "Unknown Profile field: $field"
        }
    }
    foreach ($field in $RequiredProfileFields) {
        if (-not $profile.Contains($field)) {
            throw "Provider Profile field is required: $field"
        }
    }
    if ($profile.schemaVersion -cne $SchemaVersion) {
        throw "Unsupported Provider Profile schemaVersion"
    }
    if ($profile.providerId -isnot [string] -or
        $profile.providerId -cnotmatch "^custom-[a-z0-9][a-z0-9-]{0,55}$") {
        throw "Provider Profile providerId must use the custom- prefix"
    }
    if ($profile.displayName -isnot [string] -or
        $profile.displayName.Length -lt 1 -or
        $profile.displayName.Length -gt 100 -or
        $profile.displayName -match "[\p{C}]") {
        throw "Provider Profile displayName is invalid"
    }
    if ($profile.modelId -isnot [string] -or
        $profile.modelId -cnotmatch "^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$") {
        throw "Provider Profile modelId is invalid"
    }
    if ($profile.apiKeyEnvironmentVariable -isnot [string] -or
        $profile.apiKeyEnvironmentVariable -cnotmatch "^[A-Z][A-Z0-9_]{1,63}$") {
        throw "Provider Profile API key environment variable is invalid"
    }

    $endpoint = $null
    if ($profile.baseUrl -isnot [string] -or
        -not [Uri]::TryCreate($profile.baseUrl, [UriKind]::Absolute, [ref]$endpoint)) {
        throw "Provider Profile baseUrl is invalid"
    }
    if ($endpoint.Scheme -cne "https") {
        throw "Provider Profile baseUrl must use HTTPS"
    }
    if (-not [string]::IsNullOrEmpty($endpoint.UserInfo) -or
        -not [string]::IsNullOrEmpty($endpoint.Query) -or
        -not [string]::IsNullOrEmpty($endpoint.Fragment)) {
        throw "Provider Profile baseUrl cannot contain userinfo, query, or fragment"
    }
    if (-not (Test-PublicEndpointHost -HostName $endpoint.DnsSafeHost)) {
        throw "Provider Profile baseUrl must use a public host"
    }

    $generate = [ordered]@{}
    if ($profile.Contains("generate")) {
        if ($profile.generate -isnot [Collections.IDictionary]) {
            throw "Provider Profile generate must be a JSON object"
        }
        foreach ($field in $profile.generate.Keys) {
            if ($field -cnotin $AllowedGenerateFields) {
                throw "Unknown generate field: $field"
            }
        }
        if ($profile.generate.Contains("temperature")) {
            $value = $profile.generate.temperature
            if (-not (Test-JsonNumber -Value $value) -or
                [double]$value -lt 0 -or [double]$value -gt 2) {
                throw "Provider Profile temperature must be between 0 and 2"
            }
            $generate.temperature = [double]$value
        }
        if ($profile.generate.Contains("maxTokens")) {
            $value = $profile.generate.maxTokens
            if (-not (Test-JsonNumber -Value $value) -or
                [double]$value -ne [Math]::Floor([double]$value) -or
                [long]$value -lt 1 -or [long]$value -gt 131072) {
                throw "Provider Profile maxTokens must be an integer from 1 to 131072"
            }
            $generate.max_tokens = [long]$value
        }
        if ($profile.generate.Contains("topP")) {
            $value = $profile.generate.topP
            if (-not (Test-JsonNumber -Value $value) -or
                [double]$value -le 0 -or [double]$value -gt 1) {
                throw "Provider Profile topP must be greater than 0 and at most 1"
            }
            $generate.top_p = [double]$value
        }
        if ($profile.generate.Contains("reasoningEffort")) {
            $value = $profile.generate.reasoningEffort
            if ($value -isnot [string] -or $value -cnotin @("low", "medium", "high")) {
                throw "Provider Profile reasoningEffort is invalid"
            }
            $generate.reasoning_effort = $value
        }
    }

    return [ordered]@{
        schemaVersion = $profile.schemaVersion
        providerId = $profile.providerId
        displayName = $profile.displayName
        baseUrl = $endpoint.AbsoluteUri.TrimEnd("/")
        modelId = $profile.modelId
        apiKeyEnvironmentVariable = $profile.apiKeyEnvironmentVariable
        generateKwargs = $generate
    }
}

function Get-SecretFromEnvironment {
    param([Parameter(Mandatory)][string]$Name)

    foreach ($scope in @("Process", "User", "Machine")) {
        $value = [Environment]::GetEnvironmentVariable($Name, $scope)
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value
        }
    }
    throw "Provider API key environment variable is missing"
}

function Get-CoPawBaseUri {
    param([Parameter(Mandatory)][string]$Container)

    $containerPort = if ($Container -eq "hiclaw-manager") { 18799 } else { 8088 }
    $portBindings = & docker port $Container "$containerPort/tcp" 2>&1
    $dockerExitCode = $LASTEXITCODE
    $binding = $portBindings | Select-Object -First 1
    if ($dockerExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($binding)) {
        throw "Cannot resolve CoPaw port for $Container"
    }
    if ($binding -notmatch ":(?<port>\d+)$") {
        throw "Unexpected docker port output for $Container"
    }
    return "http://127.0.0.1:$($Matches.port)"
}

function Invoke-CoPaw {
    param(
        [Parameter(Mandatory)][string]$BaseUri,
        [Parameter(Mandatory)][ValidateSet("Get", "Post", "Put")][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [object]$Body
    )

    $arguments = @{
        Method = $Method
        Uri = "$BaseUri$Path"
        TimeoutSec = 90
    }
    if ($null -ne $Body) {
        $arguments.ContentType = "application/json"
        $arguments.Body = $Body | ConvertTo-Json -Depth 10
    }
    try {
        return Invoke-RestMethod @arguments
    }
    catch {
        throw "CoPaw request failed: $Method $Path"
    }
}

function Wait-CoPawApiReady {
    param(
        [Parameter(Mandatory)][string]$BaseUri,
        [Parameter(Mandatory)][string]$Container,
        [int]$TimeoutSeconds = 120
    )

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        try {
            $null = Invoke-CoPaw -BaseUri $BaseUri -Method Get `
                -Path "/api/models" -Body $null
            return
        }
        catch {
            Start-Sleep -Seconds 3
        }
    }
    throw "CoPaw API did not become ready in $Container within $TimeoutSeconds seconds"
}

$profile = Read-ProviderProfile -Path $ProfilePath
$validationResult = [ordered]@{
    schemaVersion = $profile.schemaVersion
    providerId = $profile.providerId
    displayName = $profile.displayName
    baseUrl = $profile.baseUrl
    modelId = $profile.modelId
    apiKeyEnvironmentVariable = $profile.apiKeyEnvironmentVariable
    containers = @($Containers)
    connectionTestRequested = [bool]$RunConnectionTest
    validated = $true
}
if ($ValidateOnly) {
    $validationResult | ConvertTo-Json -Depth 5
    return
}

$secretValue = Get-SecretFromEnvironment -Name $profile.apiKeyEnvironmentVariable
$results = foreach ($container in $Containers) {
    $baseUri = Get-CoPawBaseUri -Container $container
    Wait-CoPawApiReady -BaseUri $baseUri -Container $container
    $providers = Invoke-CoPaw -BaseUri $baseUri -Method Get `
        -Path "/api/models" -Body $null
    $provider = $providers | Where-Object { $_.id -eq $profile.providerId }
    if ($null -eq $provider) {
        $null = Invoke-CoPaw -BaseUri $baseUri -Method Post `
            -Path "/api/models/custom-providers" -Body @{
                id = $profile.providerId
                name = $profile.displayName
                default_base_url = $profile.baseUrl
                api_key_prefix = ""
                chat_model = "OpenAIChatModel"
                models = @()
            }
    }

    $null = Invoke-CoPaw -BaseUri $baseUri -Method Put `
        -Path "/api/models/$($profile.providerId)/config" -Body @{
            api_key = $secretValue
            base_url = $profile.baseUrl
            chat_model = "OpenAIChatModel"
            generate_kwargs = $profile.generateKwargs
        }

    $providers = Invoke-CoPaw -BaseUri $baseUri -Method Get `
        -Path "/api/models" -Body $null
    $provider = $providers | Where-Object { $_.id -eq $profile.providerId }
    if ($null -eq $provider) {
        throw "Custom provider is unavailable in $container"
    }
    $modelIds = (@($provider.models) + @($provider.extra_models)) |
        ForEach-Object { $_.id }
    if ($profile.modelId -notin $modelIds) {
        $null = Invoke-CoPaw -BaseUri $baseUri -Method Post `
            -Path "/api/models/$($profile.providerId)/models" `
            -Body @{ id = $profile.modelId; name = $profile.modelId }
    }

    $active = Invoke-CoPaw -BaseUri $baseUri -Method Put `
        -Path "/api/models/active" -Body @{
            provider_id = $profile.providerId
            model = $profile.modelId
            scope = "global"
        }

    $connectionVerified = $false
    if ($RunConnectionTest) {
        $probe = Invoke-CoPaw -BaseUri $baseUri -Method Post `
            -Path "/api/models/$($profile.providerId)/models/test" `
            -Body @{ model_id = $profile.modelId }
        if (-not $probe.success) {
            throw "Provider model probe failed in $container"
        }
        $connectionVerified = $true
    }

    [ordered]@{
        container = $container
        provider = $active.active_llm.provider_id
        model = $active.active_llm.model
        baseUrl = $profile.baseUrl
        connectionVerified = $connectionVerified
    }
}

$results | ConvertTo-Json -Depth 5

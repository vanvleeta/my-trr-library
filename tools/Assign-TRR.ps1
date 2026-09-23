<#
.SYNOPSIS
    Assigns a TRR ID to a report folder, using this repository's configured
    ID prefix.

.DESCRIPTION
    Replaces the old TRR number inside README.md files and in filenames within
    the report folder, then renames the folder itself. Run from the root of the
    repository.

    The old ID defaults to the universal 'trr0000' placeholder used by all new
    reports. The new ID defaults to the next available number for this
    repository's prefix, read from local/config.json.

.EXAMPLE
    Assign-TRR

.EXAMPLE
    Assign-TRR -OldTrrId trr0000 -NewTrrId ACME0042
#>
function Assign-TRR {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory = $false)][String]$OldTrrId,
        [Parameter(Mandatory = $false)][String]$NewTrrId,
        [Parameter(Mandatory = $false)][String]$RepoRoot = "."
    )

    $configPath = Join-Path $RepoRoot "local/config.json"
    $indexPath = Join-Path $RepoRoot "index.json"
    $reportsPath = Join-Path $RepoRoot "reports"
    $placeholder = "trr0000"

    if (-not (Test-Path -Path $configPath)) {
        Write-Error "local/config.json not found. Run this from the repository root, or pass -RepoRoot."
        return
    }

    # Read and sanity check this repository's ID prefix.
    try {
        $config = Get-Content -Raw $configPath | ConvertFrom-Json
    } catch {
        Write-Error "local/config.json is not valid JSON: $_"
        return
    }

    $prefix = $config.id_prefix

    if ([String]::IsNullOrEmpty($prefix)) {
        Write-Error "local/config.json is missing 'id_prefix'."
        return
    }

    if ($prefix -eq "XXXX") {
        Write-Error "'id_prefix' is still set to the template placeholder 'XXXX'. Set it in local/config.json."
        return
    }

    if ($prefix -cnotmatch "^[A-Z][A-Z0-9]{1,7}$") {
        Write-Error "'id_prefix' value '$prefix' is invalid. It must be 2-8 characters, uppercase letters and digits only, starting with a letter."
        return
    }

    # Determine the old ID.
    if ([String]::IsNullOrEmpty($OldTrrId)) {
        $oldIdUpper = $placeholder.ToUpper()
        $oldIdLower = $placeholder
    } else {
        $oldIdUpper = $OldTrrId.ToUpper()
        $oldIdLower = $OldTrrId.ToLower()
    }

    # Determine the new ID.
    if ([String]::IsNullOrEmpty($NewTrrId)) {
        # Scan every index entry for the highest assigned number. Reading the
        # last entry is not safe: merge order does not keep the index sorted,
        # so the tail can hand out a number that is already in use.
        $highest = 0

        if (Test-Path -Path $indexPath) {
            $raw = Get-Content -Raw $indexPath
            if (-not [String]::IsNullOrWhiteSpace($raw)) {
                $index = ConvertFrom-Json $raw
                foreach ($entry in $index) {
                    if ($entry.id -match "^$prefix(\d+)$") {
                        $number = [int]$Matches[1]
                        if ($number -gt $highest) { $highest = $number }
                    }
                }
            }
        }

        Write-Output "Last number assigned is: $highest"
        $NewTrrId = $prefix + ($highest + 1).ToString().PadLeft(4, '0')
        Write-Output "Next available number is: $NewTrrId"
    }

    $newIdUpper = $NewTrrId.ToUpper()
    $newIdLower = $NewTrrId.ToLower()

    # The old ID may be the universal placeholder or an already-assigned ID.
    # The new ID must use this repository's prefix.
    if ($oldIdUpper -cnotmatch "^($($placeholder.ToUpper())|$prefix[0-9]{4})$") {
        Write-Error "'$oldIdUpper' is not a valid TRR number for this repository."
        return
    }

    if ($newIdUpper -cnotmatch "^$prefix[0-9]{4}$") {
        Write-Error "'$newIdUpper' does not match this repository's prefix '$prefix'."
        return
    }

    $oldFolder = Join-Path $reportsPath $oldIdLower
    $newFolder = Join-Path $reportsPath $newIdLower

    if (-not (Test-Path -Path $oldFolder)) {
        Write-Error "reports/$oldIdLower does not exist."
        return
    }

    # Without this check a rename onto an existing folder would nest the
    # report inside it rather than failing.
    if (Test-Path -Path $newFolder) {
        Write-Error "reports/$newIdLower already exists. $newIdUpper is already assigned."
        return
    }

    Write-Output "TRR Number assignment script - assigning $oldIdUpper to $newIdUpper."

    # Replace the ID inside the report markdown.
    foreach ($file in Get-ChildItem -Recurse -Path $oldFolder -Filter "README.md") {
        $content = Get-Content -Raw $file.FullName
        $content = $content.Replace($oldIdUpper, $newIdUpper)
        $content = $content.Replace($oldIdLower, $newIdLower)
        Set-Content -Path $file.FullName -Value $content -NoNewline
    }

    # Rename any file whose name carries the old ID. Filenames are lowercase.
    foreach ($file in Get-ChildItem -Recurse -File -Path $oldFolder) {
        if ($file.Name -like "*$oldIdLower*") {
            $newName = $file.Name.Replace($oldIdLower, $newIdLower)
            Rename-Item -Path $file.FullName -NewName $newName
        }
    }

    # Finally, rename the folder itself.
    Rename-Item -Path $oldFolder -NewName $newIdLower

    Write-Output "Reassignment complete."
}

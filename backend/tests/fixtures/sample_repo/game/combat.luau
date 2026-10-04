local Combat = {}

export type Attack = { damage: number, critical: boolean }

-- Damage dealt after armour; critical hits double it.
function Combat.computeDamage(attack: Attack, armour: number): number
  local base = math.max(attack.damage - armour, 0)
  if attack.critical then
    return base * 2
  end
  return base
end

return Combat

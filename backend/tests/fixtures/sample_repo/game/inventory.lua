local Inventory = {}
Inventory.__index = Inventory

function Inventory.new(capacity)
  return setmetatable({ capacity = capacity, slots = {} }, Inventory)
end

-- Adds an item if there is a free slot; returns false when the bag is full.
function Inventory:addItem(item)
  if #self.slots >= self.capacity then
    return false
  end
  table.insert(self.slots, item)
  return true
end

return Inventory

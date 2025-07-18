class Coordinate:
    # ── Init ───────────────────────────────────────────────────────────────────
    def __init__(self):
        self.coordinates = [0] * 6       # ← six positions, not five
        self.universes = 0               # real-universe overflow counter
        self.img_universe = 0            # imaginary-universe overflow counter

    # ── Copy helper ────────────────────────────────────────────────────────────
    def copy(self):
        new_coordinate = Coordinate()
        new_coordinate.coordinates = self.coordinates[:]
        new_coordinate.universes = self.universes
        new_coordinate.img_universe = self.img_universe
        return new_coordinate

    # ── Increment / Decrement / Arbitrary Δ ────────────────────────────────────
    def increment(self):   self._update_coordinates(1)
    def decrement(self):   self._update_coordinates(-1)
    def spec_change(self, value): self._update_coordinates(value)

    def _update_coordinates(self, delta):
        for i in range(len(self.coordinates)):
            self.coordinates[i] += delta
            if delta > 0 and self.coordinates[i] == 60:
                self.coordinates[i] = 0
                if i == len(self.coordinates) - 1:
                    self.universes += 1
                continue
            elif delta < 0 and self.coordinates[i] == -1:
                self.coordinates[i] = 59
                if i == len(self.coordinates) - 1:
                    self.universes -= 1
                continue
            break

    # ── Parsing / Formatting helpers ───────────────────────────────────────────
    @staticmethod
    def parse_coordinate(coord_str):
        if ' ' not in coord_str:
            raise ValueError("Invalid input. Expected space-separated coordinate.")
        parts = coord_str.split()
        if len(parts) != 6 or not all(p.isdigit() and int(p) < 60 for p in parts):
            raise ValueError("Each of the 6 numbers must be 0-59.")
        return [int(x) for x in parts]

    def get_coordinates(self):
        return ' '.join(str(c) for c in self.coordinates)

    def get_coordinates_list(self):
        return self.coordinates

    # ── Base-60 ⇄ Base-10 conversions ─────────────────────────────────────────
    def baseTenConv(self, digits=None):
        if digits is None:
            digits = self.coordinates
        return sum(d * (60 ** i) for i, d in enumerate(digits))

    def strCoord_conv(self, number):
        number %= 60 ** 6                       # ← 6-digit wrap
        digits = []
        while number:
            digits.append(number % 60)
            number //= 60
        while len(digits) < 6:                  # ← pad to 6
            digits.append(0)
        return ' '.join(str(d) for d in digits)

    def coord_conv(self, number):
        number %= 60 ** 6
        digits = []
        while number:
            digits.append(number % 60)
            number //= 60
        while len(digits) < 6:                  # ← pad to 6
            digits.append(0)
        return digits

    # ── Universe helpers ───────────────────────────────────────────────────────
    def get_univ(self):          return self.universes
    def set_univ(self, v):       self.universes = v
    def get_img_univ(self):      return self.img_universe
    def set_img_univ(self, v):   self.img_universe = v
    def reset_img_univ(self):    self.img_universe = self.universes

    # ── Distance utilities (unchanged) ─────────────────────────────────────────
    def calculate_distance(self, ref_coordinate):
        curr = self.baseTenConv()
        next_c = (self.baseTenConv(ref_coordinate) if isinstance(ref_coordinate, list)
                  else ref_coordinate.baseTenConv())
        return self.coord_conv(next_c - curr)

    def calculate_final_coordinate(self, distance):
        current_base10 = self.baseTenConv()
        return self.coord_conv(current_base10 + distance)




class FractionalCoordinate(Coordinate):
    def __init__(self):
        super().__init__()
        self.coordinates = [0.0] * 5  # Override to use floats
        self.universes = 0  # Keep track of universes (overflows)

    def copy(self):
        new_coordinate = FractionalCoordinate()
        new_coordinate.coordinates = self.coordinates[:]
        new_coordinate.universes = self.universes
        return new_coordinate

    # Override increment methods to handle floats
    def increment_by(self, delta):
        self._update_coordinates(delta)

    def decrement_by(self, delta):
        self._update_coordinates(-delta)

    def _update_coordinates(self, delta):
        total = delta
        for i in range(len(self.coordinates)):
            total += self.coordinates[i]
            self.coordinates[i] = total % 60
            total = total // 60  # Use floor division to keep total as float
        if total >= 1:
            self.universes += int(total)

    # Override baseTenConv to handle floats
    def baseTenConv(self, digits=None):
        if digits is None:
            digits = self.coordinates
        return sum(d * (60 ** i) for i, d in enumerate(digits))

    # Override get_coordinates to display floats
    def get_coordinates(self):
        # Returns the coordinates in a formatted string with up to five decimal places
        return ' '.join(f"{c:.5f}" for c in self.coordinates)

    # Override other methods as needed
    def parse_coordinate(self, coord_str):
        # Modify to handle fractional coordinates
        if '.' in coord_str:
            integer_part_str, fractional_part_str = coord_str.strip().split('.')
            integer_parts = integer_part_str.strip().split()
            fractional_parts = fractional_part_str.strip().split()
            if len(integer_parts) != 5 or len(fractional_parts) != 5:
                raise ValueError("Invalid coordinate format. Expected 5 integer and 5 fractional numbers.")
            integer_parts = [int(x) for x in integer_parts]
            fractional_parts = [float(x) for x in fractional_parts]
            self.coordinates = [i + f / 60 for i, f in zip(integer_parts, fractional_parts)]
        else:
            # Use the parent class method for integer coordinates
            self.coordinates = [float(c) for c in super().parse_coordinate(coord_str)]
        return self.coordinates

    def coord_conv(self, number):
        # Convert a base-10 number to coordinates with floats
        digits = []
        for _ in range(5):
            digits.append(number % 60)
            number //= 60
        digits.reverse()
        self.coordinates = digits
        return self.coordinates
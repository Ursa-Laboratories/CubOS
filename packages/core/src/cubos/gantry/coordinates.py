"""Shared gantry coordinate value object."""


class Coordinates:
    """Mutable 3D coordinate value object. Each axis is stored as a float
    rounded to 6 decimal places on set and on read. Supports attribute,
    integer-index, and string-key access (e.g. ``c.x``, ``c[0]``, ``c["x"]``)
    and equality by component value."""

    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

    def __str__(self):
        return f"({self.x}, {self.y}, {self.z})"

    @property
    def x(self):
        """Getter for the x-coordinate."""
        return round(float(self._x), 6)

    @x.setter
    def x(self, value):
        if not isinstance(value, (int, float)):
            raise ValueError("x-coordinate must be an int or float")
        self._x = round(value, 6)

    @property
    def y(self):
        """Getter for the y-coordinate."""
        return round(float(self._y), 6)

    @y.setter
    def y(self, value):
        if not isinstance(value, (int, float)):
            raise ValueError("y-coordinate must be an int or float")
        self._y = round(value, 6)

    @property
    def z(self):
        """Getter for the z-coordinate."""
        return round(float(self._z), 6)

    @z.setter
    def z(self, value):
        if not isinstance(value, (int, float)):
            raise ValueError("z-coordinate must be an int or float")
        self._z = round(value, 6)

    def __iter__(self):
        yield self.x
        yield self.y
        yield self.z

    def __repr__(self):
        return f"Coordinates(x={self.x}, y={self.y}, z={self.z})"

    def __eq__(self, other):
        if not isinstance(other, Coordinates):
            return False
        return self.x == other.x and self.y == other.y and self.z == other.z

    def __setitem__(self, key, value):
        if key == 0 or key == "x":
            self.x = value
        elif key == 1 or key == "y":
            self.y = value
        elif key == 2 or key == "z":
            self.z = value
        else:
            raise IndexError("Index out of range")

    def __getitem__(self, key):
        if key == 0 or key == "x":
            return self.x
        if key == 1 or key == "y":
            return self.y
        if key == 2 or key == "z":
            return self.z
        raise IndexError("Index out of range")

    def to_dict(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "z": self.z,
        }

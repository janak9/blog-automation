import os

from agency_swarm.tools import BaseTool
from pydantic import Field


class WriteFile(BaseTool):
    """
    Writes a file to the local filesystem.

    Usage:
    - This tool will overwrite the existing file if there is one at the provided path.
    - If this is an existing file, you MUST use the ReadFile tool first to read the file's contents.
    - The file_path must be an absolute path.
    """

    file_path: str = Field(..., description="Absolute path to the file to write.")
    content: str = Field(..., description="The content to write to the file")

    def run(self):
        try:
            if not os.path.isabs(self.file_path):
                return f"Error: File path must be absolute: {self.file_path}"

            file_exists = os.path.exists(self.file_path)
            if file_exists and not os.path.isfile(self.file_path):
                return f"Error: Path exists but is not a file: {self.file_path}"

            if not file_exists:
                directory = os.path.dirname(self.file_path)
                if directory and not os.path.exists(directory):
                    os.makedirs(directory, exist_ok=True)
            operation = "overwritten" if file_exists else "created"

            with open(self.file_path, "w", encoding="utf-8") as file:
                file.write(self.content)

            abs_path = os.path.abspath(self.file_path)
            try:
                if hasattr(self, "_context") and self._context is not None:
                    read_files = self._context.get("read_files", set())
                    read_files.add(abs_path)
                    self._context.set("read_files", read_files)
            except (AttributeError, TypeError):
                pass

            file_size = os.path.getsize(self.file_path)
            return f"Successfully {operation} file: {self.file_path} ({file_size} bytes)"

        except PermissionError:
            return f"Error: Permission denied writing to file: {self.file_path}"
        except Exception as e:
            return f"Error during write operation: {str(e)}"


if __name__ == "__main__":
    p = "/tmp/test_write_tool.txt"
    print(WriteFile(file_path=p, content="hello").run())
    os.path.exists(p) and os.remove(p)

import os
from typing import Optional

from agency_swarm.tools import BaseTool
from pydantic import Field


class EditFile(BaseTool):
    """
    Performs exact string replacements in files.

    Usage:
    - You must use ReadFile tool at least once in the conversation before editing.
    - When editing text, preserve the exact indentation (tabs/spaces) as it appears in the file.
    - The edit will FAIL if old_string is not unique in the file. Provide more context to make it unique or use replace_all.
    """

    file_path: str = Field(..., description="The absolute path to the file to modify")
    old_string: str = Field(..., description="The text to replace")
    new_string: str = Field(
        ..., description="The text to replace it with (must be different from old_string)"
    )
    replace_all: Optional[bool] = Field(
        False, description="Replace all occurrences of old_string (default false)"
    )

    def run(self):
        try:
            if self.old_string == self.new_string:
                return "Error: old_string and new_string must be different"
            if not os.path.isfile(self.file_path):
                return f"Error: File does not exist: {self.file_path}"

            with open(self.file_path, "r", encoding="utf-8") as file:
                content = file.read()

            if self.old_string not in content:
                return f"Error: String to replace not found in file.\nString: {repr(self.old_string)}"

            occurrences = content.count(self.old_string)
            if occurrences > 1 and not self.replace_all:
                return (
                    f"Error: String appears {occurrences} times in file. Provide more surrounding "
                    f"context to make it unique or use replace_all=True."
                )

            if self.replace_all:
                new_content = content.replace(self.old_string, self.new_string)
                count = occurrences
            else:
                new_content = content.replace(self.old_string, self.new_string, 1)
                count = 1

            with open(self.file_path, "w", encoding="utf-8") as file:
                file.write(new_content)
            return f"Successfully replaced {count} occurrence(s) in {self.file_path}"

        except Exception as e:
            return f"Error during edit operation: {str(e)}"


if __name__ == "__main__":
    p = "/tmp/test_edit_tool.txt"
    with open(p, "w") as f:
        f.write("hello world")
    print(EditFile(file_path=p, old_string="world", new_string="there").run())
    os.remove(p)

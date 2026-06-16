# Viewing the Diagram

Once erdify produces a `.puml` file, render it online, locally, or in your editor.

## Online

1. Copy the generated `.puml` content
2. Paste at [PlantUML Web Server](http://www.plantuml.com/plantuml/uml/)

## Local with PlantUML

```bash
# Install PlantUML (macOS)
brew install plantuml

# Generate PNG
plantuml erd.puml

# Generate SVG
plantuml -tsvg erd.puml
```

## VS Code Extension

Install the [PlantUML extension](https://marketplace.visualstudio.com/items?itemName=jebbs.plantuml) for live preview.

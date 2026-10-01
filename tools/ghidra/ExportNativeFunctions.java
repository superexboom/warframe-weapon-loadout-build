// Recover selected native function bodies in a derived analysis project.
// @category WFArsenal
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

public class ExportNativeFunctions extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            throw new IllegalArgumentException("output directory and function addresses required");
        }
        Path out = Path.of(args[0]);
        Files.createDirectories(out);
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        JsonArray entries = new JsonArray();
        for (int i = 1; i < args.length; i++) {
            String value = args[i].replaceFirst("^0x", "");
            Address address = toAddr(Long.parseUnsignedLong(value, 16));
            disassemble(address);
            Function function = getFunctionAt(address);
            if (function == null) {
                function = createFunction(address, "wf_" + value);
            }
            JsonObject row = new JsonObject();
            row.addProperty("address", address.toString());
            if (function == null) {
                row.addProperty("error", "function creation failed");
            } else {
                DecompileResults result = decompiler.decompileFunction(function, 60, monitor);
                row.addProperty("complete", result.decompileCompleted());
                row.addProperty("error", result.getErrorMessage());
                if (result.decompileCompleted()) {
                    String code = result.getDecompiledFunction().getC();
                    Files.writeString(out.resolve(value + ".c"), code, StandardCharsets.UTF_8);
                    row.addProperty("file", value + ".c");
                    row.addProperty("signature", result.getDecompiledFunction().getSignature());
                }
            }
            entries.add(row);
            println("native " + value + ": " + row.toString());
        }
        JsonObject report = new JsonObject();
        report.addProperty("image", currentProgram.getExecutablePath());
        report.addProperty("imageSha256", currentProgram.getExecutableSHA256());
        report.addProperty("language", currentProgram.getLanguageID().toString());
        report.addProperty("imageBase", currentProgram.getImageBase().toString());
        report.add("functions", entries);
        Files.writeString(out.resolve("manifest.json"), new GsonBuilder().setPrettyPrinting().create().toJson(report), StandardCharsets.UTF_8);
        decompiler.dispose();
    }
}

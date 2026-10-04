// Usage: wfsim-driver ENDPOINT INPUT.json OUTPUT.json
// INPUT is a JSON array of request bodies; OUTPUT is the array of responses.
fn main() {
    let a: Vec<String> = std::env::args().collect();
    let (endpoint, input, output) = (&a[1], &a[2], &a[3]);
    let rows: Vec<serde_json::Value> = serde_json::from_str(&std::fs::read_to_string(input).unwrap()).unwrap();
    let out: Vec<serde_json::Value> = rows
        .iter()
        .map(|v| wfsim_webapi::route(endpoint, v).unwrap_or_else(|| wfsim_webapi::err_json(format!("unknown endpoint: {endpoint}"))))
        .collect();
    std::fs::write(output, serde_json::to_string_pretty(&out).unwrap()).unwrap();
}

package com.anomaly;

import com.sun.net.httpserver.HttpServer;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpExchange;

import java.io.*;
import java.net.InetSocketAddress;
import java.nio.file.*;
import java.util.concurrent.Executors;
import java.util.logging.Logger;
import java.util.logging.Level;

/**
 * AnomalyDashboard — Main entry point for the Java-based anomaly detection web dashboard.
 *
 * Uses the JDK built-in com.sun.net.httpserver.HttpServer (no external dependencies)
 * to serve the dashboard UI and REST API endpoints.
 *
 * Ported from: server_space_optimizer/app.py (FastAPI application)
 *
 * This dashboard reads anomaly detection results (JSON files produced by the
 * shell scripts) and presents them through a browser-based UI with charts.
 *
 * Usage:
 *   java -cp build com.anomaly.AnomalyDashboard [options]
 *
 * Options:
 *   --port <port>         HTTP port (default: 8080)
 *   --data-dir <path>     Directory containing output JSON files
 *   --baselines <path>    Path to baselines.json
 *   --csv <path>          Path to historical CSV data
 *   --web-dir <path>      Directory containing static web files (HTML/CSS/JS)
 */
public class AnomalyDashboard {

    private static final Logger logger = Logger.getLogger(AnomalyDashboard.class.getName());

    // Configuration fields parsed from CLI arguments
    private int port = 8080;
    private String dataDir = "output";
    private String baselinesFile = "data/baselines/baselines.json";
    private String csvFile = "data/historical/sample_transactions.csv";
    private String webDir = "webapp/web";

    /**
     * Parse command-line arguments and populate configuration fields.
     */
    private void parseArgs(String[] args) {
        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--port":
                    port = Integer.parseInt(args[++i]);
                    break;
                case "--data-dir":
                    dataDir = args[++i];
                    break;
                case "--baselines":
                    baselinesFile = args[++i];
                    break;
                case "--csv":
                    csvFile = args[++i];
                    break;
                case "--web-dir":
                    webDir = args[++i];
                    break;
                case "--help":
                case "-h":
                    System.out.println("Usage: java -cp build com.anomaly.AnomalyDashboard [options]");
                    System.out.println("  --port <port>       HTTP port (default: 8080)");
                    System.out.println("  --data-dir <path>   Output JSON directory");
                    System.out.println("  --baselines <path>  Path to baselines.json");
                    System.out.println("  --csv <path>        Path to CSV data");
                    System.out.println("  --web-dir <path>    Static web files directory");
                    System.exit(0);
                    break;
                default:
                    logger.warning("Unknown option: " + args[i]);
            }
        }
    }

    /**
     * Start the HTTP server with all registered handlers.
     */
    public void start(String[] args) throws IOException {
        parseArgs(args);

        HttpServer server = HttpServer.create(new InetSocketAddress(port), 0);

        // ---- Register API endpoints (ported from server_space_optimizer/api/routes.py) ----

        // GET /api/anomalies — returns the detected anomalies JSON
        server.createContext("/api/anomalies", new FileServingHandler(
                dataDir + "/anomalies.json", "application/json"));

        // GET /api/baselines — returns the computed baselines JSON
        server.createContext("/api/baselines", new FileServingHandler(
                baselinesFile, "application/json"));

        // GET /api/report — returns the full incident report JSON
        server.createContext("/api/report", new FileServingHandler(
                dataDir + "/report.json", "application/json"));

        // GET /api/dashboard — returns a dashboard summary computed on the fly
        server.createContext("/api/dashboard", new DashboardApiHandler(
                dataDir, baselinesFile, csvFile));

        // GET /api/health — simple health check endpoint
        server.createContext("/api/health", exchange -> {
            String response = "{\"status\":\"healthy\",\"service\":\"anomaly-dashboard-java\"}";
            sendJsonResponse(exchange, 200, response);
        });

        // ---- Register static file handler for the web UI ----
        server.createContext("/", new StaticFileHandler(webDir));

        // Use a thread pool for concurrent request handling
        server.setExecutor(Executors.newFixedThreadPool(4));
        server.start();

        logger.info("Anomaly Dashboard started on http://0.0.0.0:" + port);
        logger.info("Data directory: " + dataDir);
        logger.info("Press Ctrl+C to stop");
    }

    /**
     * Send a JSON response with the given status code and body.
     */
    static void sendJsonResponse(HttpExchange exchange, int statusCode, String body) throws IOException {
        // Add CORS headers for local development
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=UTF-8");
        exchange.getResponseHeaders().set("Access-Control-Allow-Origin", "*");
        byte[] bytes = body.getBytes("UTF-8");
        exchange.sendResponseHeaders(statusCode, bytes.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
        }
    }

    public static void main(String[] args) {
        try {
            new AnomalyDashboard().start(args);
        } catch (Exception e) {
            logger.log(Level.SEVERE, "Failed to start dashboard", e);
            System.exit(1);
        }
    }

    // =========================================================================
    // Inner handler: serves a single JSON file from disk
    // =========================================================================
    static class FileServingHandler implements HttpHandler {
        private final String filePath;
        private final String contentType;

        FileServingHandler(String filePath, String contentType) {
            this.filePath = filePath;
            this.contentType = contentType;
        }

        @Override
        public void handle(HttpExchange exchange) throws IOException {
            Path path = Paths.get(filePath);
            if (!Files.exists(path)) {
                String error = "{\"error\":\"File not found: " + filePath + "\"}";
                sendJsonResponse(exchange, 404, error);
                return;
            }
            String content = new String(Files.readAllBytes(path), "UTF-8");
            sendJsonResponse(exchange, 200, content);
        }
    }

    // =========================================================================
    // Inner handler: serves static web files (HTML, CSS, JS, images)
    // =========================================================================
    static class StaticFileHandler implements HttpHandler {
        private final String webRoot;

        StaticFileHandler(String webRoot) {
            this.webRoot = webRoot;
        }

        @Override
        public void handle(HttpExchange exchange) throws IOException {
            String requestPath = exchange.getRequestURI().getPath();

            // Default to index.html for root path
            if ("/".equals(requestPath) || requestPath.isEmpty()) {
                requestPath = "/index.html";
            }

            // Resolve file path, preventing directory traversal
            Path filePath = Paths.get(webRoot, requestPath).normalize();
            if (!filePath.startsWith(Paths.get(webRoot).normalize())) {
                exchange.sendResponseHeaders(403, -1);
                return;
            }

            if (!Files.exists(filePath) || Files.isDirectory(filePath)) {
                // Try serving index.html for SPA routing
                filePath = Paths.get(webRoot, "index.html");
                if (!Files.exists(filePath)) {
                    exchange.sendResponseHeaders(404, -1);
                    return;
                }
            }

            // Determine content type from file extension
            String contentType = getContentType(filePath.toString());
            byte[] content = Files.readAllBytes(filePath);

            exchange.getResponseHeaders().set("Content-Type", contentType);
            exchange.getResponseHeaders().set("Cache-Control", "public, max-age=300");
            exchange.sendResponseHeaders(200, content.length);
            try (OutputStream os = exchange.getResponseBody()) {
                os.write(content);
            }
        }

        /**
         * Map file extensions to MIME content types.
         */
        private String getContentType(String path) {
            if (path.endsWith(".html")) return "text/html; charset=UTF-8";
            if (path.endsWith(".css"))  return "text/css; charset=UTF-8";
            if (path.endsWith(".js"))   return "application/javascript; charset=UTF-8";
            if (path.endsWith(".json")) return "application/json; charset=UTF-8";
            if (path.endsWith(".png"))  return "image/png";
            if (path.endsWith(".jpg") || path.endsWith(".jpeg")) return "image/jpeg";
            if (path.endsWith(".svg"))  return "image/svg+xml";
            if (path.endsWith(".ico"))  return "image/x-icon";
            return "application/octet-stream";
        }
    }

    // =========================================================================
    // Inner handler: computes dashboard summary from JSON data files
    // Ported from: server_space_optimizer/api/routes.py (get_dashboard_summary)
    // =========================================================================
    static class DashboardApiHandler implements HttpHandler {
        private final String dataDir;
        private final String baselinesFile;
        private final String csvFile;

        DashboardApiHandler(String dataDir, String baselinesFile, String csvFile) {
            this.dataDir = dataDir;
            this.baselinesFile = baselinesFile;
            this.csvFile = csvFile;
        }

        @Override
        public void handle(HttpExchange exchange) throws IOException {
            // Read anomalies and report to build the summary
            Path anomaliesPath = Paths.get(dataDir, "anomalies.json");
            Path reportPath = Paths.get(dataDir, "report.json");

            int totalAnomalies = 0;
            int criticalCount = 0;
            int highCount = 0;
            int totalBaselines = 0;

            // Count anomalies from the anomalies file
            if (Files.exists(anomaliesPath)) {
                String content = new String(Files.readAllBytes(anomaliesPath), "UTF-8");
                totalAnomalies = countOccurrences(content, "\"anomaly_id\"");
                criticalCount = countOccurrences(content, "\"CRITICAL\"");
                highCount = countOccurrences(content, "\"HIGH\"");
            }

            // Count baselines
            Path blPath = Paths.get(baselinesFile);
            if (Files.exists(blPath)) {
                String blContent = new String(Files.readAllBytes(blPath), "UTF-8");
                totalBaselines = countOccurrences(blContent, "\"service_name\"");
            }

            // Count CSV observations
            int totalObservations = 0;
            Path csvPath = Paths.get(csvFile);
            if (Files.exists(csvPath)) {
                totalObservations = (int) Files.lines(csvPath).count() - 1;
            }

            // Build the dashboard summary JSON
            StringBuilder json = new StringBuilder();
            json.append("{\n");
            json.append("  \"total_anomalies\": ").append(totalAnomalies).append(",\n");
            json.append("  \"critical_count\": ").append(criticalCount).append(",\n");
            json.append("  \"high_count\": ").append(highCount).append(",\n");
            json.append("  \"total_baselines\": ").append(totalBaselines).append(",\n");
            json.append("  \"total_observations\": ").append(totalObservations).append(",\n");

            // Include report data if available
            if (Files.exists(reportPath)) {
                String reportContent = new String(Files.readAllBytes(reportPath), "UTF-8");
                json.append("  \"report\": ").append(reportContent).append(",\n");
            }

            // Include raw anomalies
            if (Files.exists(anomaliesPath)) {
                String anomaliesContent = new String(Files.readAllBytes(anomaliesPath), "UTF-8");
                json.append("  \"anomalies\": ").append(anomaliesContent).append(",\n");
            } else {
                json.append("  \"anomalies\": [],\n");
            }

            // Include baselines
            if (Files.exists(blPath)) {
                String blContent = new String(Files.readAllBytes(blPath), "UTF-8");
                json.append("  \"baselines\": ").append(blContent).append("\n");
            } else {
                json.append("  \"baselines\": []\n");
            }

            json.append("}");

            sendJsonResponse(exchange, 200, json.toString());
        }

        /**
         * Count occurrences of a substring in a string.
         */
        private int countOccurrences(String text, String sub) {
            int count = 0;
            int idx = 0;
            while ((idx = text.indexOf(sub, idx)) != -1) {
                count++;
                idx += sub.length();
            }
            return count;
        }
    }
}

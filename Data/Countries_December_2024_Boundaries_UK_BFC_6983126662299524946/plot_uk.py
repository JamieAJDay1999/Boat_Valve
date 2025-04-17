import geopandas as gpd
import matplotlib.pyplot as plt
import os

# --- Configuration ---
# Set the path to your Shapefile (.shp file)
# Assumes the script is run from the 'Boat_Valve' directory based on your previous prompt
# Adjust the path if the files are located elsewhere.
shapefile_dir = "./" # Current directory
shapefile_name = "CTRY_DEC_2024_UK_BFC.shp"
shapefile_path = os.path.join(shapefile_dir, shapefile_name)

# --- Main Script ---
def plot_uk_countries(filepath):
    """
    Reads a Shapefile containing UK country boundaries and plots it.

    Args:scri
        filepath (str): The full path to the .shp file.
    """
    print(f"Attempting to read Shapefile: {filepath}")

    # Check if the file exists
    if not os.path.exists(filepath):
        print(f"ERROR: Shapefile not found at '{filepath}'")
        print("Please ensure the path is correct and all Shapefile components (.shp, .shx, .dbf, etc.) are present.")
        return

    try:
        # Read the Shapefile into a GeoDataFrame
        # GeoPandas automatically uses the companion files (.shx, .dbf, .prj)
        gdf = gpd.read_file(filepath)

        print("Shapefile read successfully.")
        print(f"Number of features (countries/shapes): {len(gdf)}")
        print(f"Coordinate Reference System (CRS): {gdf.crs}")

        # --- Plotting ---
        print("Generating plot...")

        # Create a plot figure and axes
        # Adjust figsize for desired output size (width, height in inches)
        fig, ax = plt.subplots(1, 1, figsize=(10, 12))

        # Plot the GeoDataFrame
        # You can customize appearance here (e.g., color, edgecolor)
        gdf.plot(
            ax=ax,
            color='lightgrey', # Fill color for the countries
            edgecolor='black', # Border color for the countries
            linewidth=0.5      # Border line thickness
            )

        # Customize the plot
        ax.set_title('UK Countries Map (CTRY_DEC_2024_UK_BFC)')
        ax.set_xlabel('Longitude')
        ax.set_ylabel('Latitude')
        # Optional: Turn off axis values for a cleaner map look
        # ax.set_xticks([])
        # ax.set_yticks([])
        # Or try to make axis equal (might distort based on projection)
        # ax.set_aspect('equal', adjustable='box')

        # Show the plot
        plt.tight_layout() # Adjust layout to prevent labels overlapping
        plt.show()
        print("Plot displayed.")

    except Exception as e:
        print(f"An error occurred: {e}")
        print("Ensure GeoPandas is installed correctly and the Shapefile is valid.")

# --- Run the function ---
if __name__ == "__main__":
    plot_uk_countries(shapefile_path)

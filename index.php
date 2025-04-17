<?php
// Получаем список файлов в текущей директории
$files = scandir(__DIR__);

// Удаляем точки (текущую и родительскую директорию)
$files = array_diff($files, ['.', '..']);
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Directory Listing</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 20px;
        }
        h1 {
            color: #333;
        }
        ul {
            list-style-type: none;
            padding: 0;
        }
        li {
            margin-bottom: 10px;
        }
        a {
            text-decoration: none;
            color: #007BFF;
        }
        a:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
<h1>Directory Listing</h1>
<ul>
    <li>
        <a href="..">
            ..
        </a>
    </li>
    <?php foreach ($files as $file): ?>
        <li>
            <a href="<?php echo htmlspecialchars($file); ?>">
                <?php echo htmlspecialchars($file); ?>
            </a>
        </li>
    <?php endforeach; ?>
</ul>
</body>
</html>
<?php
require_once 'config.php';
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Navigation Bar</title>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        
        body {
            font-family: Arial, sans-serif;
            padding-top: 60px; /* Чтобы контент не скрывался под навбаром */
        }
        
        nav {
            background-color: #212529;
            color: white;
            padding: 1rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 1000;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
            transition: all 0.3s ease;
        }
        
        .nav-brand {
            color: white;
            text-decoration: none;
            font-size: 1.5rem;
            font-weight: bold;
            transition: color 0.3s ease;
        }
        
        .nav-brand:hover {
            color: #28a745;
        }
        
        .nav-toggle {
            display: none;
            background: none;
            border: none;
            color: white;
            font-size: 1.5rem;
            cursor: pointer;
            transition: transform 0.3s ease;
        }
        
        .nav-toggle.active {
            transform: rotate(90deg);
        }
        
        .nav-menu {
            display: flex;
            gap: 1rem;
            list-style: none;
            transition: all 0.3s ease;
        }
        
        .search-form {
            display: flex;
            gap: 0.5rem;
        }
        
        .search-input {
            padding: 0.5rem;
            border: 1px solid #ccc;
            border-radius: 4px;
            min-width: 200px;
            transition: border-color 0.3s ease;
        }
        
        .search-input:focus {
            outline: none;
            border-color: #28a745;
            box-shadow: 0 0 0 2px rgba(40, 167, 69, 0.25);
        }
        
        .search-button {
            padding: 0.5rem 1rem;
            background-color: #28a745;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            transition: background-color 0.3s ease;
        }
        
        .search-button:hover {
            background-color: #218838;
        }
        
        @media (max-width: 768px) {
            body {
                padding-top: 110px; /* Больше места для развёрнутого меню */
            }
            
            .nav-toggle {
                display: block;
            }
            
            .nav-menu {
                display: none;
                width: 100%;
                flex-direction: column;
                padding-top: 1rem;
            }
            
            .nav-menu.active {
                display: flex;
            }
            
            .search-form {
                width: 100%;
                margin-top: 1rem;
            }
            
            .search-input {
                flex-grow: 1;
            }
        }

        /* Эффект при прокрутке (опционально) */
        nav.scrolled {
            padding: 0.5rem 1rem;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        }
    </style>
</head>
<body>
<nav id="mainNav">
    <a href="/youtube/client" class="nav-brand">LegacyProjectsTube</a>
    <button class="nav-toggle" id="navToggle">☰</button>
    <div class="nav-menu" id="navMenu">
        <form class="search-form" id="searchForm">
            <input type="search" class="search-input" placeholder="Search" id="searchInput">
            <button type="submit" class="search-button">Search</button>
        </form>
    </div>
</nav>


<script>
    // Обработчик для мобильного меню
    document.getElementById('navToggle').addEventListener('click', function() {
        this.classList.toggle('active');
        document.getElementById('navMenu').classList.toggle('active');
    });
    
    // Обработчик поиска
    document.getElementById('searchForm').addEventListener('submit', function(event) {
        event.preventDefault();
        const query = document.getElementById('searchInput').value;
        if (query) {
            window.location.href = `/youtube/client/search.php?query=${encodeURIComponent(query)}`;
        }
    });

    // Эффект при прокрутке (опционально)
    window.addEventListener('scroll', function() {
        const nav = document.getElementById('mainNav');
        if (window.scrollY > 50) {
            nav.classList.add('scrolled');
        } else {
            nav.classList.remove('scrolled');
        }
    });
</script>
</body>
</html>